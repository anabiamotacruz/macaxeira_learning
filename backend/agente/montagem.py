"""Liga as implementações das frentes às interfaces do fluxo. Só aqui o agente as conhece.

`montar_demo` monta a demonstração: tudo é sintético, em simulação e sem chave nem internet.
"""

import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agente.fluxo import Priorizador, ProvedorConsultas, RegistrarCorte
from backend.agente.persistencia import Repositorio
from backend.agente.regras import avaliar_requisitos
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteModeloSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
    RevisorSimulado,
    candidato_simulado,
)
from backend.fontes.consultas import ETAPA_GERAR, ampliar_consultas, gerar_consultas
from backend.fontes.funil import priorizar

LIMITE_ANALISES_POR_RODADA = 20
"""Quantas pessoas cada rodada leva às análises por modelo. As demais vão para a fila humana."""


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


class AnalisadorDemo:
    """Análise fictícia, sem modelo: cita o perfil inteiro quando ele contém o critério."""

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        perfil = candidato.perfil_texto.casefold()
        presentes = [c.nome for c in vaga.competencias if c.nome.casefold() in perfil]
        return Analise(
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            candidato_id=candidato.id,
            requisitos_ok={r.id: True for r in vaga.requisitos},
            notas={
                c.nome: NOTA_COM_EVIDENCIA_DEMO if c.nome in presentes else NOTA_SEM_EVIDENCIA_DEMO
                for c in vaga.competencias
            },
            evidencias=[
                Evidencia(criterio=criterio, trecho=candidato.perfil_texto, fonte=candidato.fonte)
                for criterio in [*(r.id for r in vaga.requisitos), *presentes]
            ],
            lacunas=["Análise fictícia da demonstração."],
            pontos_a_aprofundar=[],
            alertas=[],
        )


class DadosDemo:
    """Coloca as pessoas fictícias na fonte da demonstração, por empresa."""

    def __init__(self, fonte: FonteSimulada, hoje: date) -> None:
        self._fonte = fonte
        self._hoje = hoje

    def recarregar(self, empresa_id: str) -> None:
        self._fonte.candidatos[:] = [
            c for c in self._fonte.candidatos if c.empresa_id != empresa_id
        ]
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
            destino=ClienteNaraSimulado(),
            relogio=_agora,
            medidor_gasto=_sem_gasto,
            consultas=consultas_por_modelo(
                ClienteModeloSimulado({ETAPA_GERAR: {"consultas": ["python"]}})
            ),
            priorizador=priorizador_do_funil(),
        ),
        recarregar=fonte.dados.recarregar,
    )
