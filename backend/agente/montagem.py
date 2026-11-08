"""Liga as implementações das frentes às interfaces do fluxo. Só aqui o agente as conhece.

`montar_demo` monta a demonstração: tudo é sintético, em simulação e sem chave nem internet.
`montar_com_modelo` usa o modelo de verdade na análise, na revisão, nas consultas e nas dúvidas,
com os mesmos dados sintéticos. `montar_servico` escolhe: o modelo só entra com
`AGENTE_COM_MODELO=1` e a chave do provedor no ambiente. Com `NARA_MCP_URL`, a entrega, o link e
o resultado da entrevista passam pelo servidor MCP da Nara simulada, um conector por empresa.
Com `AGENTE_BUSCA_REAL=1`, a busca também usa as fontes externas da Frente 2 (Brave, Bright Data e
PDL, cada uma só com a sua chave); quem vem delas chega sem autorização, é analisado como os
demais e só recebe convite pelo e-mail que a própria pessoa publicou (`agente/contato_publicado`).
Esse convite só sai de verdade, pelo Resend, com `AGENTE_ENVIO_REAL=1`, `RESEND_API_KEY` e
`EMAIL_FROM`; sem os três, ele fica no mensageiro simulado. Pessoa sintética nunca recebe e-mail.
O botão do e-mail real leva só `CONVITE_LINK` (https), nunca o link da Nara simulada; sem ele, o
e-mail vai sem botão. Limite conhecido: o SAIR respondido por e-mail é registrado à mão e não
sobrevive a reinício, por isso o envio real manda uma única mensagem por pessoa e vaga, sem
lembrete.
Os perfis e as vagas de exemplo são os dados sintéticos da Frente 2; o convite e a Nara
simulada são da Frente 3.
"""

import json
import logging
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agente.conector_mcp import ConectorMCP, DestinoMCP, DestinoPorEmpresa
from backend.agente.configuracao import (
    PerguntaVaga,
    PropostaComObservacoes,
    propor_configuracao,
)
from backend.agente.contato_publicado import ContatoPorEmpresa
from backend.agente.fluxo import (
    Priorizador,
    ProvedorConsultas,
    RegistrarCorte,
    concorrencia_do_ambiente,
)
from backend.agente.persistencia import Repositorio
from backend.agente.regras import avaliar_requisitos, validar_criterios
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.agente.whatsapp import linha_do_convite
from backend.contato.conversa import contem_instrucao, material_da_vaga, responder_duvida
from backend.contato.mensageiro import MensageiroSimulado, PreferenciasContato, criar_convite
from backend.contato.pos_entrevista import mensagem_pos_entrevista
from backend.contato.resend import MensageiroResend
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.interfaces import (
    AgenteRecrutador,
    Analisador,
    BancoTalentos,
    ClienteModelo,
    FonteCandidatos,
    Mensageiro,
    Revisor,
)
from backend.contratos.modelos import Analise, Candidato, Evidencia, ResultadoEntrevista, Vaga
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteModeloSimulado,
    FonteSimulada,
    RevisorSimulado,
    candidato_simulado,
)
from backend.fontes.analisador import ALERTA_INSTRUCAO, INSTRUCAO, AnalisadorPorModelo, normalizar
from backend.fontes.anonimizador import (
    Pseudonimizador,
    identificadores_do_candidato,
    termos_preservados_da_vaga,
)
from backend.fontes.consultas import ETAPA_GERAR, ampliar_consultas, gerar_consultas
from backend.fontes.funil import priorizar
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.envoapi import BuscadorContatoEnvo
from backend.fontes.provedores.fonte import SupressaoPorBanco
from backend.fontes.provedores.transporte import TransporteHttp
from backend.fontes.revisor import RevisorIndependente
from backend.modelos.cliente import ClienteFeatherless
from backend.nara_simulada.mcp import configuracao_destino
from backend.nara_simulada.servico import NaraSimulada

logger = logging.getLogger(__name__)

LIMITE_ANALISES_POR_RODADA = 20
FUNIL_POR_VAGA = 10
TETO_DO_FUNIL = 50
COM_MODELO = "AGENTE_COM_MODELO"
MODELO_REVISAO = "MODELO_REVISAO"
"""Modelo só da revisão independente. Vazio: o mesmo da análise."""
ENVIO_REAL = "AGENTE_ENVIO_REAL"
RESEND_API_KEY = "RESEND_API_KEY"
EMAIL_FROM = "EMAIL_FROM"
CONVITE_LINK = "CONVITE_LINK"
NARA_MCP_URL = "NARA_MCP_URL"
BUSCA_REAL = "AGENTE_BUSCA_REAL"
ENVO_API_KEY = "ENVO_API_KEY"
CONCORRENCIA_COM_MODELO = 5
"""Análises simultâneas com o modelo ligado. A conta aguenta 25; `CONCORRENCIA_MODELO` sobrepõe."""

FonteExtra = Callable[[BancoTalentos, Repositorio], FonteCandidatos]
"""Cria uma fonte a mais com o banco e o repositório da montagem, para a supressão valer."""
"""Quantas pessoas cada rodada leva às análises por modelo. As demais vão para a fila humana."""


def pseudonimizador_de_resposta(
    pseudonimizador: Pseudonimizador, vaga: Vaga
) -> Callable[[Candidato, str], str]:
    """A mensagem da pessoa passa pela mesma pseudonimização do perfil antes de ir ao modelo."""
    preservar = termos_preservados_da_vaga(vaga)

    def pseudonimizar(candidato: Candidato, texto: str) -> str:
        return pseudonimizador.pseudonimizar_texto(
            candidato.empresa_id,
            candidato.id,
            texto,
            identificadores_do_candidato(candidato),
            preservar,
        ).texto

    return pseudonimizar


def consultas_por_modelo(cliente_modelo: ClienteModelo) -> ProvedorConsultas:
    """Primeira rodada gera; as seguintes ampliam, sem abandonar as consultas anteriores.

    As anteriores seguem na lista para o fluxo ler a página seguinte delas. Na primeira, cada
    competência da vaga também vira consulta própria: o modelo tende a gerar títulos de cargo
    com várias palavras, e a fonte só traz quem tem todas no perfil.
    """

    def consultas(vaga: Vaga, rodada: int, anteriores: Sequence[str]) -> list[str]:
        if rodada == 0 or not anteriores:
            return _com_competencias(gerar_consultas(vaga, cliente_modelo), vaga)
        return [*ampliar_consultas(vaga, list(anteriores), cliente_modelo), *anteriores]

    return consultas


def _com_competencias(consultas: list[str], vaga: Vaga) -> list[str]:
    """Acrescenta cada competência como consulta, sem repetir o que já está na lista."""
    vistas = {consulta.strip().casefold() for consulta in consultas}
    resultado = list(consultas)
    for competencia in vaga.competencias:
        chave = competencia.nome.strip().casefold()
        if chave and chave not in vistas:
            vistas.add(chave)
            resultado.append(competencia.nome.strip())
    return resultado


def tamanho_do_funil(meta_candidatos: int) -> int:
    """Quantas pessoas a rodada analisa: 10 por vaga a preencher, entre 20 e 50.

    O agente indica as melhores notas do funil, não as primeiras analisadas. O teto segura o
    gasto com o modelo.
    """
    return max(LIMITE_ANALISES_POR_RODADA, min(TETO_DO_FUNIL, FUNIL_POR_VAGA * meta_candidatos))


def priorizador_do_funil(limite: int | None = None) -> Priorizador:
    """Aplica `funil.priorizar` com a regra determinística de requisitos do agente.

    Sem `limite`, o tamanho da rodada acompanha a meta da vaga (`tamanho_do_funil`).
    """

    def priorizador(
        vaga: Vaga, candidatos: list[Candidato], hoje: date, registrar_corte: RegistrarCorte
    ) -> list[Candidato]:
        return priorizar(
            vaga,
            candidatos,
            tamanho_do_funil(vaga.meta_candidatos) if limite is None else limite,
            hoje=hoje,
            avaliar_requisitos=avaliar_requisitos,
            registrar_corte=registrar_corte,
        )

    return priorizador


NOTA_COM_EVIDENCIA_DEMO = 0.9
NOTA_SEM_EVIDENCIA_DEMO = 0.4
FONTE_DEMO = "rede_simulada"
PERFIS_DEMO = (
    ("demo-1", "Perfil fictício: cinco anos de Python em APIs.", "python", False),
    ("demo-2", "Perfil fictício: Python em sistemas de dados.", "python", False),
    ("demo-3", "Perfil fictício: oito anos de Java e Python em sistemas internos.", "java", False),
    ("demo-4", "Perfil fictício: Python em APIs; pediu para não ser contatado.", "python", True),
)
"""Pessoas fictícias da demonstração: boas, sem evidência, com requisito faltando e com opt-out."""


_PALAVRAS_VAZIAS = frozenset(
    "com para por dos das que uma sem nos nas como mais sua seu tem ter and the for vaga vagas "
    "voces qual quais".split()
)


_RELACIONADOS_DEMO = {
    "cloud": {"azure", "aws", "gcp"},
    "distr": {"micro", "filas"},
    "revie": {"revis"},
    "lider": {"lidero", "lidere", "coord"},
}
"""Termos vizinhos só desta análise simulada. Com modelo, quem relaciona os termos é ele."""


def _radicais(texto: str) -> set[str]:
    """Palavras sem acento, cortadas em cinco letras, para casar trabalho com trabalhar."""
    sem_acento = unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore")
    palavras = re.findall(r"[a-z0-9]+", sem_acento.decode())
    return {p[:5] for p in palavras if len(p) >= 3 and p not in _PALAVRAS_VAZIAS}


def _radicais_do_criterio(criterio: str) -> set[str]:
    radicais = _radicais(criterio)
    return radicais.union(*(_RELACIONADOS_DEMO.get(r, set()) for r in radicais))


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()]


def _melhor_trecho(criterio: str, frases: list[str]) -> str | None:
    """A frase do perfil que mais compartilha palavras com o critério, ou None."""
    alvo = _radicais_do_criterio(criterio)
    pontos = [(len(alvo & _radicais(frase)), -i, frase) for i, frase in enumerate(frases)]
    melhor = max(pontos, default=(0, 0, None))
    return melhor[2] if melhor[0] > 0 else None


class AnalisadorDemo:
    """Análise fictícia, sem modelo: cita a frase do perfil que trata de cada critério.

    Requisito sem frase que o cite fica sem dado, e competência sem frase recebe nota baixa.
    """

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        todas = _frases(candidato.perfil_texto)
        frases = [f for f in todas if not INSTRUCAO.search(normalizar(f))]
        alertas = [ALERTA_INSTRUCAO] if len(frases) < len(todas) else []
        evidencias = []
        requisitos_ok = {}
        for requisito in vaga.requisitos:
            trecho = _melhor_trecho(f"{requisito.descricao} {requisito.valor_esperado}", frases)
            if trecho is not None:
                requisitos_ok[requisito.id] = True
                evidencias.append(
                    Evidencia(criterio=requisito.id, trecho=trecho, fonte=candidato.fonte)
                )
        notas = {}
        for competencia in vaga.competencias:
            trecho = _melhor_trecho(competencia.nome, frases)
            notas[competencia.nome] = (
                NOTA_SEM_EVIDENCIA_DEMO if trecho is None else NOTA_COM_EVIDENCIA_DEMO
            )
            if trecho is not None:
                evidencias.append(
                    Evidencia(criterio=competencia.nome, trecho=trecho, fonte=candidato.fonte)
                )
        return Analise(
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            candidato_id=candidato.id,
            requisitos_ok=requisitos_ok,
            notas=notas,
            evidencias=evidencias,
            lacunas=["Análise simulada da demonstração, sem modelo."],
            pontos_a_aprofundar=[],
            alertas=alertas,
        )


PASTA_DADOS_SINTETICOS = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
EMPRESA_BASE_SINTETICA = "empresa-demo-1"
"""Empresa dos dados da Frente 2 cujos perfis e vagas a demonstração copia para cada sessão."""


def _ler_sinteticos(nome: str) -> list[dict]:
    return json.loads((PASTA_DADOS_SINTETICOS / nome).read_text(encoding="utf-8"))


def perfis_sinteticos(empresa_id: str) -> list[Candidato]:
    """Perfis sintéticos da Frente 2, copiados para a empresa da sessão com id próprio."""
    return [
        Candidato.model_validate(
            {**perfil, "id": f"{perfil['id']}@{empresa_id}", "empresa_id": empresa_id}
        )
        for perfil in _ler_sinteticos("candidatos.json")
        if perfil["empresa_id"] == EMPRESA_BASE_SINTETICA
    ]


def modelos_de_vaga() -> list[dict]:
    """Vagas sintéticas da Frente 2 como ponto de partida do formulário, sem id nem empresa.

    Só entram as que passam em `validar_criterios`: a vaga que a regra recusa não vira modelo.
    """
    campos = ("titulo", "descricao", "requisitos", "competencias")
    return [
        {
            **{campo: vaga[campo] for campo in campos},
            "meta_candidatos": vaga["meta_candidatos"],
            "prazo_dias": vaga["prazo_dias"],
            "max_tentativas_contato": vaga["max_tentativas_contato"],
        }
        for vaga in _ler_sinteticos("vagas.json")
        if vaga["empresa_id"] == EMPRESA_BASE_SINTETICA
        and not validar_criterios(Vaga.model_validate(vaga))
    ]


def responder_duvida_demo(vaga: Vaga, candidato: Candidato, texto: str) -> str | None:
    """Sem modelo: responde só com a frase do material da vaga que trata da pergunta.

    Usa o material e o detector de instrução da Frente 3. Sem frase que trate da pergunta,
    ou com instrução no texto, a dúvida fica para uma pessoa.
    """
    if not texto.strip() or contem_instrucao(texto):
        return None
    frases = [
        frase
        for linha in material_da_vaga(vaga).splitlines()
        for frase in _frases(linha.split(": ", 1)[-1])
    ]
    trecho = _melhor_trecho(texto, frases)
    return None if trecho is None else f"[Resposta simulada] Pelo material da vaga: {trecho}"


def redigir_convite(vaga: Vaga, candidato: Candidato, analise: Analise, link: str | None) -> str:
    """Convite da Frente 3 sem modelo: cita os critérios com evidência e o link da Nara."""
    convite = criar_convite(
        vaga,
        candidato,
        analise,
        link,
        ClienteModeloSimulado(),
        preferencias=PreferenciasContato(personalizar=False),
    )
    return convite.mensagem + linha_do_convite(vaga.empresa_id, vaga.id, candidato.id)


def redigir_retorno(vaga: Vaga, candidato: Candidato, resultado: ResultadoEntrevista) -> str:
    """Retorno da Frente 3, sem modelo: só comunica o resultado que a Nara devolveu."""
    return mensagem_pos_entrevista(vaga, resultado).replace("{nome}", candidato.nome)


CAMPOS_FORA_DA_PROPOSTA = frozenset({"email", "cargo"})
"""Contato e texto livre não servem de requisito: o primeiro é dado pessoal, o segundo não casa."""


def campos_do_banco_demo() -> dict[str, list[str]]:
    """Os atributos que os perfis da demonstração registram, com os valores que aparecem."""
    valores: dict[str, set[str]] = {}
    perfis = perfis_sinteticos(EMPRESA_BASE_SINTETICA)
    atributos = [p.atributos for p in perfis] + [
        {"linguagem": linguagem} for _, _, linguagem, _ in PERFIS_DEMO
    ]
    for registro in atributos:
        for campo, valor in registro.items():
            if campo not in CAMPOS_FORA_DA_PROPOSTA and str(valor).strip():
                valores.setdefault(campo, set()).add(str(valor).strip())
    return {campo: sorted(lista) for campo, lista in sorted(valores.items())}


class DadosDemo:
    """Coloca as pessoas fictícias na fonte da demonstração, por empresa."""

    def __init__(self, fonte: FonteSimulada, hoje: date) -> None:
        self._fonte = fonte
        self._hoje = hoje

    def recarregar(self, empresa_id: str) -> None:
        self._fonte.candidatos[:] = [
            c for c in self._fonte.candidatos if c.empresa_id != empresa_id
        ]
        self._fonte.candidatos.extend(perfis_sinteticos(empresa_id))
        self._fonte.candidatos.extend(
            candidato_simulado(
                f"{identificador}-{empresa_id}",
                empresa_id,
                nome=f"Pessoa Fictícia {identificador}",
                fonte=FONTE_DEMO,
                origem="dados_sinteticos_de_demonstracao",
                atualizado_em=self._hoje,
                autorizacao_valida_ate=self._hoje + timedelta(days=365),
                perfil_texto=perfil,
                atributos={"linguagem": linguagem},
                opt_out=opt_out,
            )
            for identificador, perfil, linguagem, opt_out in PERFIS_DEMO
        )


class FonteDemo(FonteSimulada):
    """Fonte simulada que prepara a empresa da sessão na primeira busca."""

    def __init__(self, hoje: date) -> None:
        super().__init__([])
        self.dados = DadosDemo(self, hoje)

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if not any(c.empresa_id == empresa_id for c in self.candidatos):
            self.dados.recarregar(empresa_id)
        return super().buscar(empresa_id, consulta, pagina)


def _agora() -> datetime:
    return datetime.now(UTC)


def _sem_gasto() -> float:
    """A demonstração não chama modelo: não há gasto a medir."""
    return 0.0


def _montar(
    caminho: str | Path | None,
    *,
    analisador: Analisador,
    revisor: Revisor,
    consultas: ProvedorConsultas,
    medidor_gasto: Callable[[], float],
    respondedor_duvida: Callable[[Vaga, Candidato, str], str | None],
    destino: AgenteRecrutador | None = None,
    fonte_extra: FonteExtra | None = None,
    propositor_vaga: (
        Callable[[str, str], Vaga | PerguntaVaga | PropostaComObservacoes] | None
    ) = None,
    concorrencia: int | None = None,
    buscador_contato: ContatoPorEmpresa | None = None,
    mensageiro: Mensageiro | None = None,
) -> ServicoVagas:
    if caminho is None:
        caminho = Path(tempfile.mkdtemp(prefix="macaxeira-demo-")) / "agente.db"
    fonte = FonteDemo(_agora().date())
    repositorio = Repositorio(caminho)
    banco = BancoTalentosSimulado(_agora().date())
    fontes: list[FonteCandidatos] = [fonte]
    if fonte_extra is not None:
        fontes.append(fonte_extra(banco, repositorio))
    extras = {} if concorrencia is None else {"concorrencia": concorrencia}
    return ServicoVagas(
        DependenciasFluxo(
            repositorio=repositorio,
            banco=banco,
            fontes=fontes,
            analisador=analisador,
            revisor=revisor,
            mensageiro=MensageiroSimulado() if mensageiro is None else mensageiro,
            destino=NaraSimulada() if destino is None else destino,
            relogio=_agora,
            medidor_gasto=medidor_gasto,
            consultas=consultas,
            priorizador=priorizador_do_funil(),
            redator_convite=redigir_convite,
            respondedor_duvida=respondedor_duvida,
            redator_retorno=redigir_retorno,
            propositor_vaga=propositor_vaga,
            buscador_contato=buscador_contato,
            **extras,
        ),
        recarregar=fonte.dados.recarregar,
        modelos_de_vaga=modelos_de_vaga(),
    )


def nara_por_mcp(url: str) -> DestinoPorEmpresa:
    """A Nara simulada pelo servidor MCP dela, com um conector por empresa da sessão."""
    return DestinoPorEmpresa(
        lambda empresa_id: ConectorMCP(DestinoMCP(**configuracao_destino(empresa_id, url)))
    )


def busca_real(ambiente: Mapping[str, str]) -> FonteExtra:
    """Fontes externas da Frente 2 pelo ambiente. A supressão usa o banco e os bloqueios."""

    def criar(banco: BancoTalentos, repositorio: Repositorio) -> FonteCandidatos:
        supressao = SupressaoPorBanco(banco, bloqueios=[repositorio])
        return montar_fonte_externa(ambiente, supressao=supressao, banco=banco)

    return criar


def contato_envo(ambiente: Mapping[str, str]) -> ContatoPorEmpresa | None:
    """O e-mail publicado pela EnvoAPI, só com `ENVO_API_KEY`. A chave não sai daqui."""
    chave = ambiente.get(ENVO_API_KEY, "").strip()
    if not chave:
        return None
    return ContatoPorEmpresa(BuscadorContatoEnvo(chave, TransporteHttp()))


def mensageiro_do_ambiente(ambiente: Mapping[str, str]) -> Mensageiro | None:
    """O Resend, só com `AGENTE_ENVIO_REAL=1`, a chave e o remetente. A chave não sai daqui."""
    if ambiente.get(ENVIO_REAL, "").strip() != "1":
        return None
    chave = ambiente.get(RESEND_API_KEY, "").strip()
    remetente = ambiente.get(EMAIL_FROM, "").strip()
    if not chave or not remetente:
        logger.warning("%s=1, mas falta a chave ou o remetente: o envio segue simulado", ENVIO_REAL)
        return None
    link = ambiente.get(CONVITE_LINK, "").strip() or None
    if link is not None and not link.startswith("https://"):
        logger.warning("%s precisa ser https: o e-mail real vai sem botão", CONVITE_LINK)
        link = None
    try:
        return MensageiroResend(chave, remetente, link_convite=link)
    except ValueError:
        logger.warning(
            "%s=1, mas o remetente ou o link é inválido: o envio segue simulado", ENVIO_REAL
        )
        return None


def montar_demo(
    caminho: str | Path | None = None,
    *,
    destino: AgenteRecrutador | None = None,
    fonte_extra: FonteExtra | None = None,
    buscador_contato: ContatoPorEmpresa | None = None,
    mensageiro: Mensageiro | None = None,
) -> ServicoVagas:
    """Serviço da demonstração. Sem `caminho`, o banco fica numa pasta temporária.

    Sem busca real, `buscador_contato` fica vazio: a demo sintética nunca chama a EnvoAPI. Sem
    `mensageiro`, o envio é simulado; com o Resend, só o convite real sai, e o sintético não.
    """
    return _montar(
        caminho,
        analisador=AnalisadorDemo(),
        revisor=RevisorSimulado(),
        consultas=consultas_por_modelo(
            ClienteModeloSimulado({ETAPA_GERAR: {"consultas": ["python"]}})
        ),
        medidor_gasto=_sem_gasto,
        respondedor_duvida=responder_duvida_demo,
        destino=destino,
        fonte_extra=fonte_extra,
        buscador_contato=buscador_contato,
        mensageiro=mensageiro,
    )


def montar_com_modelo(
    caminho: str | Path | None = None,
    *,
    cliente: ClienteModelo,
    medidor_gasto: Callable[[], float],
    destino: AgenteRecrutador | None = None,
    fonte_extra: FonteExtra | None = None,
    buscador_contato: ContatoPorEmpresa | None = None,
    mensageiro: Mensageiro | None = None,
    cliente_revisao: ClienteModelo | None = None,
) -> ServicoVagas:
    """A demonstração com o modelo raciocinando. Pessoas, contato e Nara seguem simulados.

    `cliente_revisao` deixa a revisão independente com outro modelo: o revisor que inventa
    ressalva derruba a nota de todo mundo, e a revisão pede mais rigor que a análise.

    O gasto vem do cliente: passou do limite do mandato, a vaga pausa. A concorrência padrão é
    `CONCORRENCIA_COM_MODELO`; `CONCORRENCIA_MODELO`, quando definida, vale no lugar dela.
    """
    definida = (os.environ.get("CONCORRENCIA_MODELO") or "").strip()
    concorrencia = concorrencia_do_ambiente() if definida else CONCORRENCIA_COM_MODELO

    def responder(vaga: Vaga, candidato: Candidato, texto: str) -> str | None:
        return responder_duvida(vaga, texto, cliente)

    return _montar(
        caminho,
        analisador=AnalisadorPorModelo(cliente),
        revisor=RevisorIndependente(cliente_revisao or cliente),
        consultas=consultas_por_modelo(cliente),
        medidor_gasto=medidor_gasto,
        respondedor_duvida=responder,
        destino=destino,
        fonte_extra=fonte_extra,
        propositor_vaga=lambda descricao, empresa_id: propor_configuracao(
            descricao, empresa_id, cliente, campos_do_banco=campos_do_banco_demo()
        ),
        concorrencia=concorrencia,
        buscador_contato=buscador_contato,
        mensageiro=mensageiro,
    )


def montar_servico(
    caminho: str | Path | None = None,
    *,
    ambiente: Mapping[str, str] | None = None,
    criar_cliente: Callable[..., ClienteModelo] = ClienteFeatherless,
    criar_busca: Callable[[Mapping[str, str]], FonteExtra] = busca_real,
) -> ServicoVagas:
    """Escolhe a montagem pelo ambiente. Sem opt-in ou sem chave, fica a demonstração sem modelo."""
    ambiente = os.environ if ambiente is None else ambiente
    url_nara = ambiente.get(NARA_MCP_URL, "").strip()
    destino = nara_por_mcp(url_nara) if url_nara else None
    extra = criar_busca(ambiente) if ambiente.get(BUSCA_REAL, "").strip() == "1" else None
    contato = None if extra is None else contato_envo(ambiente)
    envio = mensageiro_do_ambiente(ambiente)
    demo = {"destino": destino, "fonte_extra": extra, "buscador_contato": contato}
    if ambiente.get(COM_MODELO, "").strip() != "1":
        return montar_demo(caminho, mensageiro=envio, **demo)
    try:
        cliente = criar_cliente()
        modelo_revisao = (ambiente.get(MODELO_REVISAO) or "").strip()
        revisao = (
            criar_cliente(modelo=modelo_revisao)
            if modelo_revisao and modelo_revisao != getattr(cliente, "modelo", None)
            else None
        )
    except ModeloIndisponivel as erro:
        logger.warning("%s=1, mas segue a demonstração sem modelo: %s", COM_MODELO, erro)
        return montar_demo(caminho, mensageiro=envio, **demo)

    def gasto() -> float:
        return sum(
            float(getattr(c, "custo_total_usd", 0.0)) for c in (cliente, revisao) if c is not None
        )

    return montar_com_modelo(
        caminho,
        cliente=cliente,
        medidor_gasto=gasto,
        destino=destino,
        fonte_extra=extra,
        buscador_contato=contato,
        mensageiro=envio,
        cliente_revisao=revisao,
    )
