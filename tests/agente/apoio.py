"""Dublês e exemplos sintéticos para os testes do agente."""

from datetime import UTC, datetime, timedelta

from backend.contratos.modelos import (
    Analise,
    Candidato,
    Competencia,
    Evidencia,
    PacoteContexto,
    Requisito,
    Vaga,
)
from backend.contratos.simulacoes import ClienteNaraSimulado, candidato_simulado

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TRECHO_REQUISITO = "Cinco anos com Python"
TRECHO_COMPETENCIA = "Liderou APIs"
PERFIL_EXEMPLO = f"{TRECHO_REQUISITO}. {TRECHO_COMPETENCIA} em produção."


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
