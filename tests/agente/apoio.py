"""Dublês e exemplos sintéticos para os testes do agente."""

from datetime import UTC, datetime, timedelta

from backend.agente.auditoria import RegistroRastro
from backend.agente.montagem import consultas_por_modelo, priorizador_do_funil
from backend.agente.persistencia import Repositorio
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Competencia,
    Evidencia,
    PacoteContexto,
    Requisito,
    Vaga,
)
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteModeloSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
    candidato_simulado,
)
from backend.fontes.consultas import ETAPA_GERAR
from backend.modelos.resiliencia import Resiliencia

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TRECHO_REQUISITO = "Cinco anos com Python"
TRECHO_COMPETENCIA = "Liderou APIs"
PERFIL_EXEMPLO = f"{TRECHO_REQUISITO}. {TRECHO_COMPETENCIA} em produção."


class CapturaRastro:
    """Destino externo de rastro: guarda todos os registros, como a auditoria os emite."""

    def __init__(self) -> None:
        self.registros: list[RegistroRastro] = []

    def registrar(self, registro: RegistroRastro) -> None:
        self.registros.append(registro)


class Relogio:
    """Relógio fixo que só anda quando o teste manda."""

    def __init__(self, agora: datetime = AGORA) -> None:
        self.agora = agora

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, **duracao: float) -> None:
        self.agora += timedelta(**duracao)


def vaga_exemplo(**campos) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Python",
        "descricao": "Vaga sintética",
        "requisitos": [
            Requisito(id="r1", descricao="Sabe Python", campo="python", valor_esperado="sim")
        ],
        "competencias": [Competencia(nome="backend", peso=1.0)],
        "meta_candidatos": 2,
        "prazo_dias": 10,
        "max_tentativas_contato": 2,
    }
    dados.update(campos)
    return Vaga(**dados)


def candidato_exemplo(candidato_id: str, **campos) -> Candidato:
    """Candidato sintético de fonte verificável, que atende ao requisito da vaga de exemplo."""
    empresa_id = campos.pop("empresa_id", "empresa-a")
    dados = {
        "fonte": "rede_simulada",
        "perfil_texto": PERFIL_EXEMPLO,
        "atributos": {"python": "sim"},
    }
    dados.update(campos)
    return candidato_simulado(candidato_id, empresa_id, **dados)


class AnalisadorComEvidencias:
    """Analisador com trechos literais do perfil. A nota padrão cai na faixa verde."""

    def __init__(self, notas: dict[str, float] | None = None, nota_padrao: float = 0.9) -> None:
        self.notas = notas or {}
        self.nota_padrao = nota_padrao
        self.analisados: list[str] = []

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        self.analisados.append(candidato.id)
        evidencias = [
            *(
                Evidencia(criterio=r.id, trecho=TRECHO_REQUISITO, fonte=candidato.fonte)
                for r in vaga.requisitos
            ),
            *(
                Evidencia(criterio=c.nome, trecho=TRECHO_COMPETENCIA, fonte=candidato.fonte)
                for c in vaga.competencias
            ),
        ]
        nota = self.notas.get(candidato.id, self.nota_padrao)
        return Analise(
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            candidato_id=candidato.id,
            requisitos_ok={r.id: True for r in vaga.requisitos},
            notas={c.nome: nota for c in vaga.competencias},
            evidencias=evidencias,
            lacunas=["Sem dado de inglês"],
            pontos_a_aprofundar=["Experiência com filas"],
            alertas=[],
        )


class RevisorSemRessalva:
    def __init__(self) -> None:
        self.revisados: list[str] = []

    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise:
        self.revisados.append(candidato.id)
        return analise


class NaraFalhaDepoisDeAceitar(ClienteNaraSimulado):
    """Guarda o pacote e responde falha, como uma resposta perdida no caminho de volta."""

    def __init__(self, falhas: int = 1) -> None:
        super().__init__()
        self.falhas = falhas
        self.chamadas = 0

    def entregar(self, pacote: PacoteContexto) -> bool:
        self.chamadas += 1
        super().entregar(pacote)
        if self.falhas > 0:
            self.falhas -= 1
            return False
        return True


class NaraForaDoAr(ClienteNaraSimulado):
    """Destino que nunca aceita a entrega."""

    def entregar(self, pacote: PacoteContexto) -> bool:
        return False


CONSULTA_DE_TESTE = "python"
TITULO_DE_TESTE = "Pessoa Desenvolvedora (fictícia)"

PEDIDO_VAGA = {
    "titulo": TITULO_DE_TESTE,
    "descricao": "Vaga sintética",
    "requisitos": [
        {
            "id": "python",
            "descricao": "Experiência com Python",
            "campo": "linguagem",
            "valor_esperado": "python",
        }
    ],
    "competencias": [{"nome": "APIs", "peso": 1.0}],
    "meta_candidatos": 1,
    "prazo_dias": 14,
    "max_tentativas_contato": 2,
}


def pedido_mandato(**politica) -> dict:
    return {
        "assinante": "Pessoa Responsável Fictícia",
        "limite_gasto_usd": 5.0,
        "politica": {
            "limiar_verde": 0.8,
            "piso_nota": 0.5,
            "max_indicacoes": 2,
            "max_ampliacoes": 1,
            **politica,
        },
    }


def candidatos_de_teste() -> list[Candidato]:
    """Uma pessoa na faixa verde, uma para a fila e duas que o funil tira."""

    def pessoa(candidato_id: str, **campos) -> Candidato:
        dados = {"nome": f"Pessoa Fictícia {candidato_id}", "atributos": {"linguagem": "python"}}
        return candidato_exemplo(candidato_id, **{**dados, **campos})

    return [
        pessoa("verde"),
        pessoa("fila"),
        pessoa("java", atributos={"linguagem": "java"}, perfil_texto=f"{PERFIL_EXEMPLO} Java"),
        pessoa("saiu", opt_out=True),
    ]


def servico_de_teste(caminho, *, candidatos=None, **pecas) -> ServicoVagas:
    """Serviço com o funil e as consultas reais, e simulações nas demais peças."""
    dependencias = {
        "repositorio": Repositorio(caminho),
        "banco": BancoTalentosSimulado(),
        "fontes": [FonteSimulada(candidatos_de_teste() if candidatos is None else candidatos)],
        "analisador": AnalisadorComEvidencias(notas={"fila": 0.6}),
        "revisor": RevisorSemRessalva(),
        "mensageiro": MensageiroSimulado(),
        "destino": ClienteNaraSimulado(),
        "relogio": Relogio(),
        "medidor_gasto": lambda: 0.0,
        "consultas": consultas_por_modelo(
            ClienteModeloSimulado({ETAPA_GERAR: {"consultas": [CONSULTA_DE_TESTE]}})
        ),
        "priorizador": priorizador_do_funil(),
        "resiliencia": Resiliencia(dormir=lambda _: None),
    }
    extras = {
        chave: pecas.pop(chave)
        for chave in ("metricas", "recarregar", "gerar_id")
        if chave in pecas
    }
    return ServicoVagas(DependenciasFluxo(**{**dependencias, **pecas}), **extras)
