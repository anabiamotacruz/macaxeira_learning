"""Nara simulada (T3.3): agente recrutador fictício para a demo e os testes.

Oferece link fictício, recebe pacotes sem duplicar e devolve resultados
reproduzíveis por semente, com uma nota por critério do pacote, para alimentar
o aprendizado. Tudo é marcado como simulado e separado por empresa.
"""

import hashlib

from backend.contratos.modelos import PacoteContexto, ResultadoEntrevista

BASE_LINK = "https://nara.simulada.local/agendar"
NOTA_APROVACAO = 0.5


def _exigir_empresa(empresa_id: str) -> None:
    if not empresa_id or not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório em toda leitura e escrita")


def _nota(*partes: str) -> float:
    digest = hashlib.sha256(":".join(partes).encode()).hexdigest()
    return round(int(digest[:8], 16) / 0xFFFFFFFF, 2)


class NaraSimulada:
    """Implementa `AgenteRecrutador`. `falhas_restantes` simula a Nara fora do ar."""

    def __init__(self, semente: int = 0, falhas_restantes: int = 0) -> None:
        self.semente = semente
        self.falhas_restantes = falhas_restantes
        self._entregues: dict[str, dict[str, PacoteContexto]] = {}

    def _da_empresa(self, empresa_id: str) -> dict[str, PacoteContexto]:
        _exigir_empresa(empresa_id)
        return self._entregues.setdefault(empresa_id, {})

    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str:
        return f"{BASE_LINK}/{vaga_id}/{candidato_id}"

    def entregar(self, pacote: PacoteContexto) -> bool:
        if not pacote.simulado:
            raise ValueError("a Nara simulada só recebe pacotes simulados")
        entregues = self._da_empresa(pacote.empresa_id)
        if pacote.chave_idempotencia in entregues:
            return True
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            return False
        entregues[pacote.chave_idempotencia] = pacote
        return True

    def entregues(self, empresa_id: str) -> list[PacoteContexto]:
        return list(self._da_empresa(empresa_id).values())

    def _resultado(self, pacote: PacoteContexto) -> ResultadoEntrevista:
        criterios = sorted(pacote.motivo_por_criterio) or ["geral"]
        base = (str(self.semente), pacote.empresa_id, pacote.vaga_id, pacote.candidato_id)
        notas = {criterio: _nota(*base, criterio) for criterio in criterios}
        media = sum(notas.values()) / len(notas)
        return ResultadoEntrevista(
            empresa_id=pacote.empresa_id,
            vaga_id=pacote.vaga_id,
            candidato_id=pacote.candidato_id,
            notas=notas,
            aprovado=media >= NOTA_APROVACAO,
            simulado=True,
        )

    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoEntrevista]:
        pacotes = [p for p in self._da_empresa(empresa_id).values() if p.vaga_id == vaga_id]
        return [self._resultado(p) for p in sorted(pacotes, key=lambda p: p.candidato_id)]
