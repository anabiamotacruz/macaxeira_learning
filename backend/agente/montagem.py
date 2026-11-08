"""Liga as implementações das frentes às interfaces do fluxo. Só aqui o agente as conhece.

`montar_demo` monta a demonstração: tudo é sintético, em simulação e sem chave nem internet.
`montar_com_modelo` usa o modelo de verdade na análise, na revisão, nas consultas e nas dúvidas,
com os mesmos dados sintéticos. `montar_servico` escolhe: o modelo só entra com
`AGENTE_COM_MODELO=1` e a chave do provedor no ambiente. Com `NARA_MCP_URL`, a entrega, o link e
o resultado da entrevista passam pelo servidor MCP da Nara simulada, um conector por empresa.
Com `AGENTE_BUSCA_REAL=1`, a busca também usa as fontes externas da Frente 2 (Brave, Bright Data e
PDL, cada uma só com a sua chave); quem vem delas chega sem autorização e o funil o segura.
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
from backend.agente.configuracao import PerguntaVaga, propor_configuracao
from backend.agente.fluxo import Priorizador, ProvedorConsultas, RegistrarCorte
from backend.agente.persistencia import Repositorio
from backend.agente.regras import avaliar_requisitos, validar_criterios
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.contato.conversa import contem_instrucao, material_da_vaga, responder_duvida
from backend.contato.mensageiro import MensageiroSimulado, PreferenciasContato, criar_convite
from backend.contato.pos_entrevista import mensagem_pos_entrevista
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.interfaces import (
    AgenteRecrutador,
    Analisador,
    BancoTalentos,
    ClienteModelo,
    FonteCandidatos,
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
from backend.fontes.provedores.fonte import SupressaoPorBanco
from backend.fontes.revisor import RevisorIndependente
from backend.modelos.cliente import ClienteFeatherless
from backend.nara_simulada.mcp import configuracao_destino
from backend.nara_simulada.servico import NaraSimulada

logger = logging.getLogger(__name__)

LIMITE_ANALISES_POR_RODADA = 20
COM_MODELO = "AGENTE_COM_MODELO"
NARA_MCP_URL = "NARA_MCP_URL"
BUSCA_REAL = "AGENTE_BUSCA_REAL"

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


def priorizador_do_funil(limite: int = LIMITE_ANALISES_POR_RODADA) -> Priorizador:
    """Aplica `funil.priorizar` com a regra determinística de requisitos do agente."""

    def priorizador(
        vaga: Vaga, candidatos: list[Candidato], hoje: date, registrar_corte: RegistrarCorte
    ) -> list[Candidato]:
        return priorizar(
            vaga,
            candidatos,
            limite,
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
    return convite.mensagem


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
    propositor_vaga: Callable[[str, str], Vaga | PerguntaVaga] | None = None,
) -> ServicoVagas:
    if caminho is None:
        caminho = Path(tempfile.mkdtemp(prefix="macaxeira-demo-")) / "agente.db"
    fonte = FonteDemo(_agora().date())
    repositorio = Repositorio(caminho)
    banco = BancoTalentosSimulado(_agora().date())
    fontes: list[FonteCandidatos] = [fonte]
    if fonte_extra is not None:
        fontes.append(fonte_extra(banco, repositorio))
    return ServicoVagas(
        DependenciasFluxo(
            repositorio=repositorio,
            banco=banco,
            fontes=fontes,
            analisador=analisador,
            revisor=revisor,
            mensageiro=MensageiroSimulado(),
            destino=NaraSimulada() if destino is None else destino,
            relogio=_agora,
            medidor_gasto=medidor_gasto,
            consultas=consultas,
            priorizador=priorizador_do_funil(),
            redator_convite=redigir_convite,
            respondedor_duvida=respondedor_duvida,
            redator_retorno=redigir_retorno,
            propositor_vaga=propositor_vaga,
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


def montar_demo(
    caminho: str | Path | None = None,
    *,
    destino: AgenteRecrutador | None = None,
    fonte_extra: FonteExtra | None = None,
) -> ServicoVagas:
    """Serviço da demonstração. Sem `caminho`, o banco fica numa pasta temporária."""
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
    )


def montar_com_modelo(
    caminho: str | Path | None = None,
    *,
    cliente: ClienteModelo,
    medidor_gasto: Callable[[], float],
    destino: AgenteRecrutador | None = None,
    fonte_extra: FonteExtra | None = None,
) -> ServicoVagas:
    """A demonstração com o modelo raciocinando. Pessoas, contato e Nara seguem simulados.

    O gasto vem do cliente: passou do limite do mandato, a vaga pausa.
    """

    def responder(vaga: Vaga, candidato: Candidato, texto: str) -> str | None:
        return responder_duvida(vaga, texto, cliente)

    return _montar(
        caminho,
        analisador=AnalisadorPorModelo(cliente),
        revisor=RevisorIndependente(cliente),
        consultas=consultas_por_modelo(cliente),
        medidor_gasto=medidor_gasto,
        respondedor_duvida=responder,
        destino=destino,
        fonte_extra=fonte_extra,
        propositor_vaga=lambda descricao, empresa_id: propor_configuracao(
            descricao, empresa_id, cliente, campos_do_banco=campos_do_banco_demo()
        ),
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
    if ambiente.get(COM_MODELO, "").strip() != "1":
        return montar_demo(caminho, destino=destino, fonte_extra=extra)
    try:
        cliente = criar_cliente()
    except ModeloIndisponivel as erro:
        logger.warning("%s=1, mas segue a demonstração sem modelo: %s", COM_MODELO, erro)
        return montar_demo(caminho, destino=destino, fonte_extra=extra)

    def gasto() -> float:
        return float(getattr(cliente, "custo_total_usd", 0.0))

    return montar_com_modelo(
        caminho, cliente=cliente, medidor_gasto=gasto, destino=destino, fonte_extra=extra
    )
