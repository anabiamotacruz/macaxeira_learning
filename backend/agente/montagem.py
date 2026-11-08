"""Liga as implementações das frentes às interfaces do fluxo. Só aqui o agente as conhece.

`montar_demo` monta a demonstração: tudo é sintético, em simulação e sem chave nem internet.
Os perfis e as vagas de exemplo são os dados sintéticos da Frente 2; o convite e a Nara
simulada são da Frente 3.
"""

import json
import re
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agente.fluxo import Priorizador, ProvedorConsultas, RegistrarCorte
from backend.agente.persistencia import Repositorio
from backend.agente.regras import avaliar_requisitos, validar_criterios
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.contato.mensageiro import MensageiroSimulado, PreferenciasContato, criar_convite
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteModeloSimulado,
    FonteSimulada,
    RevisorSimulado,
    candidato_simulado,
)
from backend.fontes.analisador import ALERTA_INSTRUCAO, INSTRUCAO, normalizar
from backend.fontes.anonimizador import (
    Pseudonimizador,
    identificadores_do_candidato,
    termos_preservados_da_vaga,
)
from backend.fontes.consultas import ETAPA_GERAR, ampliar_consultas, gerar_consultas
from backend.fontes.funil import priorizar
from backend.nara_simulada.servico import NaraSimulada

LIMITE_ANALISES_POR_RODADA = 20
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

    As anteriores seguem na lista para o fluxo ler a página seguinte delas.
    """

    def consultas(vaga: Vaga, rodada: int, anteriores: Sequence[str]) -> list[str]:
        if rodada == 0 or not anteriores:
            return gerar_consultas(vaga, cliente_modelo)
        return [*ampliar_consultas(vaga, list(anteriores), cliente_modelo), *anteriores]

    return consultas


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
    "com para por dos das que uma sem nos nas como mais sua seu tem ter and the for".split()
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


def montar_demo(caminho: str | Path | None = None) -> ServicoVagas:
    """Serviço da demonstração. Sem `caminho`, o banco fica numa pasta temporária."""
    if caminho is None:
        caminho = Path(tempfile.mkdtemp(prefix="macaxeira-demo-")) / "agente.db"
    fonte = FonteDemo(_agora().date())
    return ServicoVagas(
        DependenciasFluxo(
            repositorio=Repositorio(caminho),
            banco=BancoTalentosSimulado(_agora().date()),
            fontes=[fonte],
            analisador=AnalisadorDemo(),
            revisor=RevisorSimulado(),
            mensageiro=MensageiroSimulado(),
            destino=NaraSimulada(),
            relogio=_agora,
            medidor_gasto=_sem_gasto,
            consultas=consultas_por_modelo(
                ClienteModeloSimulado({ETAPA_GERAR: {"consultas": ["python"]}})
            ),
            priorizador=priorizador_do_funil(),
            redator_convite=redigir_convite,
        ),
        recarregar=fonte.dados.recarregar,
        modelos_de_vaga=modelos_de_vaga(),
    )
