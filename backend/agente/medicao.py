"""Ciclo de taxa de erro: mede o agente em casos sintéticos e sustenta a escolha do limiar.

Os cálculos são funções puras e sem estado, para serem conferidos à mão. Nada aqui usa modelo
de IA: o agente avaliado é injetado em `rodar` e nunca recebe o gabarito.

Margem de erro: intervalo de Wilson com 95% de confiança, z = 1,96 (exatamente
`NormalDist().inv_cdf(0.975)`). Com `x` erros em `n` casos e `p = x / n`:

    centro = (p + z² / 2n) / (1 + z² / n)
    margem = z * raiz(p(1 - p) / n + z² / 4n²) / (1 + z² / n)
    intervalo = centro - margem, centro + margem

Escolhido porque continua útil com zero erros e com poucos casos: 0 em 10 dá teto de 27,75%,
quando a aproximação normal daria 0%. O intervalo supõe casos independentes, e casos gerados
pelos mesmos cenários não são. Por isso, ele é o melhor cenário, não uma garantia.

Tipos de erro (`TipoErro`) e o denominador de cada taxa. Um caso pode ter mais de um tipo:

    indicacao_errada         indicados pelo agente com gabarito diferente de indicar
    descarte_errado          descartados pelo agente com gabarito diferente de descartar
    violacao_eliminatoria    indicados sem todos os requisitos ou com autorização bloqueada
    contato_opt_out          entre os casos respondidos com opt-out, os indicados
    mudanca_nome_genero      pares de `par_vies` com ao menos um lado respondido, em que a
                             decisão muda ou só um dos lados responde
    afirmacao_sem_evidencia  indicados sem evidência ou com trecho que não está no perfil

Revisão, cobertura e falhas dividem todos os casos e somam 1: cobertura é quem o agente
resolveu sozinho, revisão é quem foi para uma pessoa, falha é quem ficou sem resposta.
Falha nunca entra como acerto nem some da conta. Sem casos, a taxa é nula, nunca zero.

Gabarito: `respostas_certas.json` traz estados por requisito e autorização, sem decisão final.
`derivar_gabarito` deriva a decisão, nesta ordem, sem olhar a resposta do agente:

    1. autorização bloqueada                                     -> descartar
    2. algum requisito `nao_atende`                              -> descartar
    3. algum requisito `desconhecido`                            -> pedir_humano
    4. exagero, instrução no currículo ou perfil desatualizado   -> pedir_humano
    5. cargo incomum, erro e sinônimo, duplicata ou referência   -> indicar

O passo 4 é premissa nossa: nesses cenários os requisitos estão atendidos, mas o arquivo pede
uma verificação que o agente não deveria resolver sozinho. Nada disso foi validado por recrutador.
"""

import hashlib
import json
import logging
import random
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)
from contextlib import closing, contextmanager
from datetime import datetime
from math import sqrt
from pathlib import Path
from statistics import NormalDist
from typing import NamedTuple

from pydantic import ValidationError

from backend.agente.auditoria import contexto_rastro, rastreado
from backend.agente.regras import TipoEvidencia, classificar_evidencia
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    Candidato,
    CasoAvaliacao,
    Contrato,
    DecisaoPortao,
    Evidencia,
    MetricasMedicao,
    Particao,
    RelatorioMedicao,
    RespostaAgente,
    ResultadoCaso,
    ResultadoProva,
    ResumoConjunto,
    TaxaMedida,
    TipoDecisao,
    TipoErro,
    Vaga,
    VersaoPrompt,
)

logger = logging.getLogger(__name__)

Z_95 = NormalDist().inv_cdf(0.975)
FALHA_RESPOSTA_INVALIDA = "resposta_invalida"
REGRA_ABAIXO_DO_LIMIAR = "abaixo_do_limiar"
TIPOS_QUE_PRECISAM_SER_ZERO = (
    TipoErro.VIOLACAO_ELIMINATORIA,
    TipoErro.CONTATO_OPT_OUT,
    TipoErro.MUDANCA_NOME_GENERO,
    TipoErro.AFIRMACAO_SEM_EVIDENCIA,
)

AgenteAvaliado = Callable[[Candidato, Vaga], RespostaAgente]
"""Recebe só o perfil e a vaga, posicionalmente. Dele saem decisão, regra, nota e evidências.

Para calibrar o limiar, o agente responde como se a nota bastasse (limiar zero na política).
Quem corta pela nota é `aplicar_limiar`, sobre os mesmos resultados.
"""

CacheRodada = MutableMapping[tuple[str, str], RespostaAgente]
"""Respostas por (hash da versão, hash da entrada). Nunca guarda gabarito nem falha."""


REGRA_GABARITO = "derivar_gabarito_v1"
SEMENTE_PARTICAO = 42
"""Fixada antes de qualquer rodada, igual à semente do gerador."""
PROPORCOES = {Particao.AJUSTE: 0.6, Particao.VALIDACAO: 0.2, Particao.PROVA: 0.2}
"""Alvo em número de casos. Com poucos grupos, as proporções reais ficam longe dele."""
AUTORIZACAO_VALIDA = "valida_na_data_referencia"
AUTORIZACAO_BLOQUEADA = "bloqueada"
ESTADOS_REQUISITO = frozenset({"atende", "nao_atende", "desconhecido"})
CENARIOS_INDICAVEIS = frozenset({"cargo_incomum", "erro_e_sinonimo", "duplicata", "referencia"})
CENARIOS_PEDEM_PESSOA = frozenset({"exagero", "instrucao_no_curriculo", "desatualizado"})
CENARIOS_RESOLVIDOS_ANTES = frozenset(
    {"opt_out", "autorizacao_vencida", "sem_autorizacao", "sem_requisito", "informacao_ausente"}
)
INDICADOS_PARA_MARGEM_DE_3_PONTOS = 384
"""n = 1,96² * p * (1 - p) / margem², com p = 10% e margem de 0,03: dá 384,16."""
_MARCA_DE_PROJETO = re.compile(r"\s*Projeto fictício [^.]*\.\s*$")
"""O gerador só varia o nome do projeto no fim do texto: fora isso, o texto se repete."""


class ProvaJaAberta(ErroContrato):
    """Esta versão já abriu a prova. A tentativa foi recusada e registrada."""


class DadosInvalidos(ErroContrato):
    """Arquivos de avaliação ausentes, incoerentes ou com algo que não sabemos derivar."""


def _hash(dados: object) -> str:
    texto = json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _contagem_valida(valor: object) -> bool:
    return type(valor) is int and valor >= 0


def intervalo_wilson(erros: int, total: int) -> tuple[float, float] | tuple[None, None]:
    """Intervalo de Wilson de 95% para `erros` em `total`. Sem casos, devolve (None, None)."""
    if not _contagem_valida(erros) or not _contagem_valida(total) or erros > total:
        raise ValueError("erros e total precisam ser inteiros com 0 <= erros <= total")
    if total == 0:
        return None, None
    p = erros / total
    z2 = Z_95**2
    denominador = 1 + z2 / total
    centro = (p + z2 / (2 * total)) / denominador
    margem = Z_95 * sqrt(p * (1 - p) / total + z2 / (4 * total**2)) / denominador
    # Nos extremos o limite é exato: evita resíduo de arredondamento fora de [0, 1].
    inferior = 0.0 if erros == 0 else min(p, centro - margem)
    superior = 1.0 if erros == total else max(p, centro + margem)
    return inferior, superior


def medir_taxa(erros: int, total: int) -> TaxaMedida:
    """Taxa com casos e intervalo. Sem casos, não foi medida: tudo nulo, nunca zero."""
    inferior, superior = intervalo_wilson(erros, total)
    return TaxaMedida(
        valor=None if total == 0 else erros / total,
        casos=total,
        wilson_inferior=inferior,
        wilson_superior=superior,
    )


def _unico(valores: Iterable[str], nome: str) -> str | None:
    distintos = set(valores)
    if len(distintos) > 1:
        raise ValueError(f"métricas não misturam mais de uma {nome}")
    return next(iter(distintos), None)


def hash_conjunto(ids_casos: Iterable[str]) -> str:
    """Identifica um conjunto de casos, sem depender da ordem."""
    return _hash(sorted(ids_casos))


def _taxa_de_pares(resultados: Sequence[ResultadoCaso]) -> TaxaMedida:
    pares: dict[str, list[ResultadoCaso]] = defaultdict(list)
    for resultado in resultados:
        if resultado.par_vies is not None:
            pares[resultado.par_vies].append(resultado)
    # Falha de um lado conta como mudança: se trocar o nome derruba o caso, o resultado mudou.
    medidos = [
        par for par in pares.values() if len(par) >= 2 and any(r.decisao is not None for r in par)
    ]
    mudaram = sum(len({r.decisao for r in par}) > 1 for par in medidos)
    return medir_taxa(mudaram, len(medidos))


def _violou_eliminatorio(resultado: ResultadoCaso) -> bool:
    return resultado.autorizacao_bloqueada or not resultado.requisitos_cumpridos


def calcular_metricas(resultados: Sequence[ResultadoCaso]) -> MetricasMedicao:
    """Calcula as taxas de uma rodada, de uma só partição e versão, sem aplicar limiar."""
    particao = _unico((r.particao for r in resultados), "partição")
    versao_hash = _unico((r.versao_hash for r in resultados), "versão")
    total = len(resultados)

    def com_decisao(tipo: TipoDecisao) -> list[ResultadoCaso]:
        return [r for r in resultados if r.decisao == tipo]

    indicados = com_decisao(TipoDecisao.INDICAR)
    descartados = com_decisao(TipoDecisao.DESCARTAR)
    revisados = com_decisao(TipoDecisao.PEDIR_HUMANO)
    falhas = sum(r.decisao is None for r in resultados)
    com_opt_out = [r for r in resultados if r.opt_out and r.decisao is not None]

    return MetricasMedicao(
        particao=particao,
        versao_hash=versao_hash,
        conjunto_hash=hash_conjunto(r.caso_id for r in resultados) if resultados else None,
        casos=total,
        erros={
            TipoErro.INDICACAO_ERRADA: medir_taxa(
                sum(r.gabarito != TipoDecisao.INDICAR for r in indicados), len(indicados)
            ),
            TipoErro.DESCARTE_ERRADO: medir_taxa(
                sum(r.gabarito != TipoDecisao.DESCARTAR for r in descartados), len(descartados)
            ),
            TipoErro.VIOLACAO_ELIMINATORIA: medir_taxa(
                sum(_violou_eliminatorio(r) for r in indicados), len(indicados)
            ),
            TipoErro.CONTATO_OPT_OUT: medir_taxa(
                sum(r.decisao == TipoDecisao.INDICAR for r in com_opt_out), len(com_opt_out)
            ),
            TipoErro.MUDANCA_NOME_GENERO: _taxa_de_pares(resultados),
            TipoErro.AFIRMACAO_SEM_EVIDENCIA: medir_taxa(
                sum(r.afirmacao_sem_evidencia for r in indicados), len(indicados)
            ),
        },
        revisao=medir_taxa(len(revisados), total),
        cobertura=medir_taxa(len(indicados) + len(descartados), total),
        falhas=medir_taxa(falhas, total),
    )


def versionar_prompt(etapa: str, texto: str, modelo: str) -> VersaoPrompt:
    """Versão imutável de um prompt. Outro texto ou outro modelo geram outro hash."""
    if not texto.strip():
        raise ValueError("prompt vazio não tem versão")
    return VersaoPrompt(
        etapa=etapa, modelo=modelo, hash=_hash({"etapa": etapa, "modelo": modelo, "texto": texto})
    )


@rastreado("medicao_agente")
def _chamar_agente(agente: AgenteAvaliado, perfil: Candidato, vaga: Vaga) -> object:
    return agente(perfil, vaga)


def _resposta_valida(resposta: object) -> RespostaAgente | None:
    if not isinstance(resposta, RespostaAgente):
        return None
    try:
        return RespostaAgente.model_validate(resposta.model_dump())
    except ValidationError:
        return None


def _afirma_sem_fonte(evidencias: Sequence[Evidencia], perfil: Candidato) -> bool:
    if not evidencias:
        return True
    return any(classificar_evidencia(e, perfil) == TipoEvidencia.INFERIDA for e in evidencias)


def _resultado(
    caso: CasoAvaliacao,
    versao: VersaoPrompt,
    rastro_id: str,
    resposta: RespostaAgente | None,
    falha: str | None,
) -> ResultadoCaso:
    return ResultadoCaso(
        caso_id=caso.id,
        particao=caso.particao,
        versao_hash=versao.hash,
        gabarito=caso.gabarito,
        decisao=resposta.decisao if resposta else None,
        regra=resposta.regra if resposta else None,
        nota=resposta.nota if resposta else None,
        evidencias=resposta.evidencias if resposta else [],
        falha=falha,
        requisitos_cumpridos=set(caso.requisitos_atendidos) == {r.id for r in caso.vaga.requisitos},
        autorizacao_bloqueada=caso.autorizacao_bloqueada,
        opt_out=caso.perfil.opt_out,
        afirmacao_sem_evidencia=(
            _afirma_sem_fonte(resposta.evidencias, caso.perfil) if resposta else False
        ),
        armadilha=caso.armadilha,
        par_vies=caso.par_vies,
        rastro_id=rastro_id,
    )


def _hash_entrada(caso: CasoAvaliacao) -> str:
    return _hash(
        {"perfil": caso.perfil.model_dump(mode="json"), "vaga": caso.vaga.model_dump(mode="json")}
    )


def _executar(
    caso: CasoAvaliacao, agente: AgenteAvaliado, versao: VersaoPrompt, cache: CacheRodada | None
) -> ResultadoCaso:
    """Resolve um caso pelo cache ou chama o agente. Só o perfil e a vaga saem daqui, em cópias."""
    chave = (versao.hash, _hash_entrada(caso))
    with contexto_rastro(
        empresa_id=caso.vaga.empresa_id,
        execucao_id=f"medicao-{versao.hash[:12]}",
        vaga_id=caso.vaga.id,
        candidato_id=caso.perfil.id,
    ) as contexto:
        if cache is not None and chave in cache:
            return _resultado(caso, versao, contexto.rastro_id, cache[chave], None)
        perfil = caso.perfil.model_copy(deep=True)
        vaga = caso.vaga.model_copy(deep=True)
        try:
            bruta = _chamar_agente(agente, perfil, vaga)
        except Exception as erro:  # conta e segue: a mensagem pode ter chave, só o tipo fica
            logger.warning("falha no caso %s: %s", caso.id, type(erro).__name__)
            return _resultado(caso, versao, contexto.rastro_id, None, type(erro).__name__)
        resposta = _resposta_valida(bruta)
        if resposta is None:
            return _resultado(caso, versao, contexto.rastro_id, None, FALHA_RESPOSTA_INVALIDA)
        if cache is not None:
            cache[chave] = resposta
        return _resultado(caso, versao, contexto.rastro_id, resposta, None)


def rodar(
    casos: Sequence[CasoAvaliacao],
    agente: AgenteAvaliado,
    versao: VersaoPrompt,
    cache: CacheRodada | None = None,
) -> list[ResultadoCaso]:
    """Roda o agente nos casos, sem entregar o gabarito. Falhas viram resultado com `falha`.

    Casos de prova ficam de fora: só `rodar_prova` os abre, uma vez e sem caso a caso.
    """
    if any(caso.particao == Particao.PROVA for caso in casos):
        raise ValueError("casos de prova só abrem em rodar_prova")
    return [_executar(caso, agente, versao, cache) for caso in casos]


def aplicar_limiar(
    resultados: Sequence[ResultadoCaso], limiar: float | None
) -> list[ResultadoCaso]:
    """Manda para revisão quem foi indicado com nota abaixo do limiar ou sem nota.

    Como na regra da faixa verde, a nota igual ao limiar passa, e limiar nulo significa que
    ninguém fica na faixa verde. Descartes e falhas não mudam.
    """
    if limiar is not None and not 0 <= limiar <= 1:
        raise ValueError("limiar precisa estar entre 0 e 1")

    def fica(resultado: ResultadoCaso) -> bool:
        if resultado.decisao != TipoDecisao.INDICAR:
            return True
        return limiar is not None and resultado.nota is not None and resultado.nota >= limiar

    return [
        r
        if fica(r)
        else r.model_copy(
            update={"decisao": TipoDecisao.PEDIR_HUMANO, "regra": REGRA_ABAIXO_DO_LIMIAR}
        )
        for r in resultados
    ]


def _limiar_viavel(metricas: MetricasMedicao, meta: float) -> bool:
    teto = metricas.erros[TipoErro.INDICACAO_ERRADA].wilson_superior
    if teto is None or teto > meta:
        return False
    return all(metricas.erros[tipo].valor == 0 for tipo in TIPOS_QUE_PRECISAM_SER_ZERO)


def escolher_limiar(resultados: Sequence[ResultadoCaso], meta: float) -> float | None:
    """Escolhe, no ajuste, o limiar com mais casos sem revisão dentro da meta de erro.

    Um limiar é viável se o teto de Wilson da indicação errada, e não só o valor observado,
    fica até a `meta`, e toda taxa que precisa ser zero foi medida e deu zero: é a mesma regra de
    `passa_no_portao`, porque ausência de medida não é zero. Sem limiar viável,
    devolve None, nunca o menos pior. Baixar o limiar só aumenta a cobertura, e os candidatos
    são as notas dos indicados: por isso, o menor viável é o de maior cobertura.
    """
    if not 0 < meta < 1:
        raise ValueError("meta precisa estar entre 0 e 1")
    if any(r.particao != Particao.AJUSTE for r in resultados):
        raise ValueError("limiar só se escolhe com resultados de ajuste")
    candidatos = {
        r.nota for r in resultados if r.decisao == TipoDecisao.INDICAR and r.nota is not None
    }
    for limiar in sorted(candidatos):
        if _limiar_viavel(calcular_metricas(aplicar_limiar(resultados, limiar)), meta):
            return limiar
    return None


def _piora(nome: str, antes: TaxaMedida, depois: TaxaMedida, maior_e_melhor: bool) -> str | None:
    if depois.valor is None:
        return None if antes.valor is None else f"{nome}: deixou de ser medida"
    if antes.valor is None:
        return None if maior_e_melhor or depois.valor == 0 else f"{nome}: erro sem base anterior"
    piorou = depois.valor < antes.valor if maior_e_melhor else depois.valor > antes.valor
    return f"{nome}: piorou de {antes.valor:.4f} para {depois.valor:.4f}" if piorou else None


def passa_no_portao(antes: MetricasMedicao, depois: MetricasMedicao) -> DecisaoPortao:
    """Barra a mudança se qualquer régua piorar ou se algo que precisa ser zero não for zero.

    Compara valores observados, sem tolerância: manter a versão atual custa pouco. Taxa que
    precisa ser zero e não foi medida também barra, porque ausência de medida não é zero.
    Passar quer dizer "não piorou nestas réguas"; não comprova melhora.
    """
    motivos: list[str] = []
    if antes.conjunto_hash != depois.conjunto_hash:
        motivos.append("conjunto de casos diferente: a comparação não vale")
    for tipo in TIPOS_QUE_PRECISAM_SER_ZERO:
        valor = depois.erros[tipo].valor
        if valor is None:
            motivos.append(f"{tipo.value}: precisa ser zero e não foi medida")
        elif valor > 0:
            motivos.append(f"{tipo.value}: precisa ser zero e foi {valor:.4f}")
    reguas = [
        (
            TipoErro.INDICACAO_ERRADA.value,
            antes.erros[TipoErro.INDICACAO_ERRADA],
            depois.erros[TipoErro.INDICACAO_ERRADA],
            False,
        ),
        (
            TipoErro.DESCARTE_ERRADO.value,
            antes.erros[TipoErro.DESCARTE_ERRADO],
            depois.erros[TipoErro.DESCARTE_ERRADO],
            False,
        ),
        ("revisao", antes.revisao, depois.revisao, False),
        ("falhas", antes.falhas, depois.falhas, False),
        ("cobertura", antes.cobertura, depois.cobertura, True),
    ]
    motivos += [motivo for regua in reguas if (motivo := _piora(*regua)) is not None]
    return DecisaoPortao(passou=not motivos, motivos=motivos)


class RegistroProvas:
    """Guarda, em SQLite, quem abriu a prova, para a regra valer depois de reiniciar.

    A chave primária torna a abertura atômica. Prompts diferentes contam como versões
    diferentes: trocar um espaço abre de novo, e por isso `abrir` devolve quantas versões
    já olharam o conjunto, para o relatório declarar.
    """

    def __init__(self, caminho: Path | str) -> None:
        self._caminho = Path(caminho)
        with self._transacao() as conexao:
            conexao.executescript(
                """
                CREATE TABLE IF NOT EXISTS aberturas (
                    versao_hash TEXT PRIMARY KEY,
                    conjunto_hash TEXT NOT NULL,
                    momento TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recusas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    versao_hash TEXT NOT NULL,
                    conjunto_hash TEXT NOT NULL,
                    momento TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._caminho)) as conexao, conexao:
            yield conexao

    def abrir(self, versao_hash: str, conjunto_hash: str, momento: datetime) -> int:
        """Registra a abertura e devolve quantas versões já abriram o conjunto.

        Levanta `ProvaJaAberta` na segunda abertura da versão, depois de registrar a recusa.
        """
        dados = (versao_hash, conjunto_hash, momento.isoformat())
        with self._transacao() as conexao:
            nova = conexao.execute(
                "INSERT OR IGNORE INTO aberturas (versao_hash, conjunto_hash, momento) "
                "VALUES (?, ?, ?)",
                dados,
            ).rowcount
            if not nova:
                conexao.execute(
                    "INSERT INTO recusas (versao_hash, conjunto_hash, momento) VALUES (?, ?, ?)",
                    dados,
                )
            total = conexao.execute(
                "SELECT COUNT(*) FROM aberturas WHERE conjunto_hash = ?", (conjunto_hash,)
            ).fetchone()[0]
        if not nova:
            raise ProvaJaAberta(f"a versão {versao_hash[:12]} já abriu a prova")
        return total

    def recusas(self, versao_hash: str) -> int:
        with self._transacao() as conexao:
            return conexao.execute(
                "SELECT COUNT(*) FROM recusas WHERE versao_hash = ?", (versao_hash,)
            ).fetchone()[0]


def rodar_prova(
    casos: Sequence[CasoAvaliacao],
    agente: AgenteAvaliado,
    versao: VersaoPrompt,
    limiar: float | None,
    registro: RegistroProvas,
    agora: datetime,
) -> ResultadoProva:
    """Abre a prova uma única vez por versão, com limiar já congelado, e devolve só agregados.

    A abertura é gravada antes da primeira chamada: se a rodada cair no meio, a prova está
    gasta. Sem cache, para nenhuma resposta da prova voltar a outra rodada.
    """
    if not casos:
        raise ValueError("prova sem casos não abre")
    if any(caso.particao != Particao.PROVA for caso in casos):
        raise ValueError("rodar_prova só aceita casos de prova")
    aberturas = registro.abrir(versao.hash, hash_conjunto(c.id for c in casos), agora)
    resultados = [_executar(caso, agente, versao, None) for caso in casos]
    return ResultadoProva(
        versao=versao,
        limiar=limiar,
        metricas=calcular_metricas(aplicar_limiar(resultados, limiar)),
        aberta_em=agora,
        aberturas_do_conjunto=aberturas,
    )


class GabaritoDerivado(NamedTuple):
    decisao: TipoDecisao
    motivo: str


def derivar_gabarito(
    requisitos: Mapping[str, str], autorizacao: str, cenario: str
) -> GabaritoDerivado:
    """Deriva a decisão certa dos estados do arquivo, pela ordem descrita no início do módulo.

    Não recebe a resposta do agente. Recusa o que não sabe derivar, em vez de adivinhar.
    """
    conhecidos = CENARIOS_INDICAVEIS | CENARIOS_PEDEM_PESSOA | CENARIOS_RESOLVIDOS_ANTES
    if cenario not in conhecidos:
        raise DadosInvalidos(f"cenário sem regra de gabarito: {cenario!r}")
    if autorizacao not in (AUTORIZACAO_VALIDA, AUTORIZACAO_BLOQUEADA):
        raise DadosInvalidos(f"autorização desconhecida: {autorizacao!r}")
    estados = set(requisitos.values())
    if not estados or not estados <= ESTADOS_REQUISITO:
        raise DadosInvalidos(f"estados de requisito inválidos: {sorted(map(str, estados))}")

    if autorizacao == AUTORIZACAO_BLOQUEADA:
        return GabaritoDerivado(TipoDecisao.DESCARTAR, "autorizacao_bloqueada")
    if "nao_atende" in estados:
        return GabaritoDerivado(TipoDecisao.DESCARTAR, "requisito_nao_atendido")
    if "desconhecido" in estados:
        return GabaritoDerivado(TipoDecisao.PEDIR_HUMANO, "requisito_sem_informacao")
    if cenario in CENARIOS_PEDEM_PESSOA:
        return GabaritoDerivado(TipoDecisao.PEDIR_HUMANO, f"verificacao_aberta:{cenario}")
    if cenario in CENARIOS_INDICAVEIS:
        return GabaritoDerivado(TipoDecisao.INDICAR, "requisitos_atendidos_sem_ressalva")
    raise DadosInvalidos(f"cenário {cenario!r} contradiz os estados do arquivo")


def particionar(chaves: Sequence[Collection[str]], semente: int) -> list[Particao]:
    """Sorteia a partição de cada caso, mantendo juntos os que dividem qualquer chave.

    Os grupos são as componentes ligadas por chaves em comum, e o resultado não depende da
    ordem de entrada. Cada partição recebe um grupo; o restante vai para a mais distante da
    sua proporção, com empate na ordem de `PROPORCOES`. Sem três grupos, não há como separar.
    """
    pais: dict[str, str] = {}

    def raiz(chave: str) -> str:
        pais.setdefault(chave, chave)
        while pais[chave] != chave:
            pais[chave] = pais[pais[chave]]
            chave = pais[chave]
        return chave

    for chaves_do_caso in chaves:
        for chave in chaves_do_caso:
            # A menor chave fica como raiz: o grupo não depende da ordem de entrada.
            a, b = sorted((raiz(chave), raiz(min(chaves_do_caso))))
            pais[b] = a

    raizes = [raiz(min(chaves_do_caso)) for chaves_do_caso in chaves]
    tamanhos = Counter(raizes)
    grupos = sorted(tamanhos)
    if len(grupos) < len(PROPORCOES):
        raise DadosInvalidos(f"só {len(grupos)} grupos independentes para três partições")

    random.Random(semente).shuffle(grupos)
    destino: dict[str, Particao] = {}
    ocupacao = dict.fromkeys(PROPORCOES, 0)
    obrigatorias = [Particao.PROVA, Particao.VALIDACAO, Particao.AJUSTE]
    for indice, grupo in enumerate(grupos):
        if indice < len(obrigatorias):
            particao = obrigatorias[indice]
        else:
            particao = max(PROPORCOES, key=lambda p: PROPORCOES[p] * len(chaves) - ocupacao[p])
        destino[grupo] = particao
        ocupacao[particao] += tamanhos[grupo]
    return [destino[grupo] for grupo in raizes]


def _texto_modelo(perfil: Candidato) -> str:
    return _MARCA_DE_PROJETO.sub("", perfil.perfil_texto)


def _chaves_do_caso(perfil: Candidato, vaga: Vaga, par_vies: str | None) -> set[str]:
    """Pessoa, vaga e par ficam juntos. Texto igual em outra empresa também: seria quase cópia."""
    chaves = {
        f"pessoa|{perfil.empresa_id}|{perfil.id}",
        f"vaga|{vaga.empresa_id}|{vaga.id}",
        f"texto|{_texto_modelo(perfil)}",
    }
    if par_vies is not None:
        chaves.add(f"par|{par_vies}")
    return chaves


class _RequisitoArquivo(Contrato):
    estado: str
    trecho: str


class _CasoArquivo(Contrato):
    indice: int
    empresa_id: str
    candidato_id: str
    fonte: str
    vaga_id: str
    cenario: str
    requisitos: dict[str, _RequisitoArquivo]
    autorizacao_para_vaga: str
    verificacoes: list[str]
    par_vies: str | None = None


class _ArquivoGabarito(Contrato):
    versao: int
    semente: int
    quantidade: int
    data_referencia: str
    origem: str
    casos: list[_CasoArquivo]


def _ler_json(pasta: Path, nome: str) -> object:
    try:
        return json.loads((pasta / nome).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise DadosInvalidos(f"não foi possível ler {nome}: {type(erro).__name__}") from None


def _montar_caso(
    registro: _CasoArquivo,
    perfil: Candidato,
    vaga: Vaga,
    particao: Particao,
    arquivo: _ArquivoGabarito,
) -> CasoAvaliacao:
    if {r.id for r in vaga.requisitos} != set(registro.requisitos):
        raise DadosInvalidos(f"requisitos do registro {registro.indice} diferem dos da vaga")
    bloqueada = registro.autorizacao_para_vaga == AUTORIZACAO_BLOQUEADA
    if perfil.opt_out and not bloqueada:
        raise DadosInvalidos(f"registro {registro.indice} tem opt-out sem bloqueio")
    derivado = derivar_gabarito(
        {nome: r.estado for nome, r in registro.requisitos.items()},
        registro.autorizacao_para_vaga,
        registro.cenario,
    )
    return CasoAvaliacao(
        id=f"{perfil.empresa_id}:{perfil.id}:{vaga.id}:{perfil.fonte}",
        perfil=perfil,
        vaga=vaga,
        gabarito=derivado.decisao,
        motivo_gabarito=derivado.motivo,
        requisitos_atendidos=sorted(
            nome for nome, r in registro.requisitos.items() if r.estado == "atende"
        ),
        autorizacao_bloqueada=bloqueada,
        particao=particao,
        armadilha=registro.cenario,
        par_vies=registro.par_vies,
        semente=arquivo.semente,
        versao_gerador=str(arquivo.versao),
    )


def _casos_dos_arquivos(pasta: Path, semente: int) -> list[CasoAvaliacao]:
    candidatos = _ler_json(pasta, "candidatos.json")
    vagas = _ler_json(pasta, "vagas.json")
    arquivo = _ArquivoGabarito.model_validate(_ler_json(pasta, "respostas_certas.json"))
    perfis = [Candidato.model_validate(c) for c in candidatos]
    vagas_por_id = {v.id: v for v in map(Vaga.model_validate, vagas)}
    if not arquivo.quantidade == len(arquivo.casos) == len(perfis):
        raise DadosInvalidos("candidatos e gabarito têm quantidades diferentes")

    pares = []
    for perfil, registro in zip(perfis, arquivo.casos, strict=True):
        vaga = vagas_por_id.get(registro.vaga_id)
        if vaga is None or vaga.empresa_id != perfil.empresa_id:
            raise DadosInvalidos(f"registro {registro.indice} cita vaga inexistente")
        if (perfil.empresa_id, perfil.id, perfil.fonte) != (
            registro.empresa_id,
            registro.candidato_id,
            registro.fonte,
        ):
            raise DadosInvalidos(f"registro {registro.indice} não bate com o candidato")
        pares.append((registro, perfil, vaga))

    particoes = particionar([_chaves_do_caso(p, v, r.par_vies) for r, p, v in pares], semente)
    casos = [
        _montar_caso(registro, perfil, vaga, particao, arquivo)
        for (registro, perfil, vaga), particao in zip(pares, particoes, strict=True)
    ]
    if len({caso.id for caso in casos}) != len(casos):
        raise DadosInvalidos("há casos repetidos no gabarito")
    return casos


def ler_casos(pasta: Path | str, semente: int = SEMENTE_PARTICAO) -> list[CasoAvaliacao]:
    """Lê os arquivos da Frente 2 e monta os casos, com partições reproduzíveis.

    Lê `candidatos.json`, `vagas.json` e `respostas_certas.json`, alinhados pela posição, e
    recusa qualquer incoerência. Só monta os casos: quem guarda a prova é `rodar_prova`.
    """
    try:
        return _casos_dos_arquivos(Path(pasta), semente)
    except (ValidationError, TypeError) as erro:  # sem valores: o perfil não vai para o erro
        raise DadosInvalidos(f"dados fora do formato: {type(erro).__name__}") from None


def _assinatura(caso: CasoAvaliacao) -> str:
    perfil = caso.perfil
    return _hash(
        {
            "texto": _texto_modelo(perfil),
            "estado": perfil.estado,
            "opt_out": perfil.opt_out,
            "autorizou": perfil.autorizou_contato,
            "validade": str(perfil.autorizacao_valida_ate),
            "atualizado": str(perfil.atualizado_em),
            "bloqueada": caso.autorizacao_bloqueada,
            "requisitos": sorted((r.id, r.campo, r.valor_esperado) for r in caso.vaga.requisitos),
        }
    )


def resumir_casos(casos: Sequence[CasoAvaliacao]) -> ResumoConjunto:
    """Conta registros, pares e casos independentes. Mais de uma partição vira partição nula."""
    particoes = {caso.particao for caso in casos}
    composicao: dict[TipoDecisao, int] = defaultdict(int)
    for caso in casos:
        composicao[caso.gabarito] += 1
    return ResumoConjunto(
        particao=next(iter(particoes)) if len(particoes) == 1 else None,
        registros=len(casos),
        pares_pessoa_vaga=len({(c.perfil.empresa_id, c.perfil.id, c.vaga.id) for c in casos}),
        casos_independentes=len({_assinatura(c) for c in casos}),
        textos_distintos=len({_texto_modelo(c.perfil) for c in casos}),
        cenarios=len({c.armadilha for c in casos if c.armadilha is not None}),
        vagas=len({(c.vaga.empresa_id, c.vaga.id) for c in casos}),
        composicao_gabarito=dict(composicao),
    )


def _limites(
    metricas: MetricasMedicao, conjunto: ResumoConjunto, aberturas: int | None
) -> list[str]:
    indicados = metricas.erros[TipoErro.INDICACAO_ERRADA].casos
    limites = [
        "Dados sintéticos, feitos pelo próprio projeto e com cenários repetidos: "
        "não são amostra estatística do mercado nem currículos reais.",
        "Gabarito sintético, derivado por regra e não validado por recrutador: "
        "acertar aqui não prova acerto no mundo real.",
        f"{conjunto.registros} registros, {conjunto.pares_pessoa_vaga} pares pessoa e vaga e só "
        f"{conjunto.casos_independentes} casos independentes, com {conjunto.textos_distintos} "
        f"textos distintos em {conjunto.cenarios} cenários e {conjunto.vagas} vagas. Os "
        "intervalos de Wilson contam registros e supõem independência: são otimistas.",
        f"{indicados} casos indicados: medir 10% com margem de 3 pontos pede cerca de "
        f"{INDICADOS_PARA_MARGEM_DE_3_PONTOS}.",
        "Composição enriquecida de propósito: cobertura e revisão não são taxas de produção.",
    ]
    if aberturas is not None and aberturas > 1:
        limites.append(
            f"{aberturas} versões já abriram esta prova: cada olhada aumenta a chance de um "
            "prompt ruim passar, e casos novos seriam necessários."
        )
    return limites


def gerar_relatorio(
    metricas: MetricasMedicao,
    versao: VersaoPrompt,
    conjunto: ResumoConjunto,
    limiar: float | None,
    meta: float | None,
    aberturas_do_conjunto: int | None = None,
) -> RelatorioMedicao:
    """Monta o relatório para o painel. `model_dump_json()` dá o JSON, sem nada caso a caso.

    O relatório sempre declara os limites da medição, inclusive quantos casos são independentes.
    """
    if metricas.versao_hash is not None and metricas.versao_hash != versao.hash:
        raise ValueError("métricas de outra versão do prompt")
    if metricas.particao != conjunto.particao:
        raise ValueError("métricas e resumo não são da mesma partição")
    if metricas.casos != conjunto.registros:
        raise ValueError("métricas e resumo têm números de registros diferentes")
    return RelatorioMedicao(
        gabarito_validado_por_recrutador=False,
        regra_gabarito=REGRA_GABARITO,
        versao=versao,
        limiar=limiar,
        meta=meta,
        metricas=metricas,
        conjunto=conjunto,
        aberturas_do_conjunto=aberturas_do_conjunto,
        limites=_limites(metricas, conjunto, aberturas_do_conjunto),
    )
