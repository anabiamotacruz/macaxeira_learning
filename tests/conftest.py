import pytest

from backend.agente import auditoria
from tests.agente.apoio import CapturaRastro


@pytest.fixture(autouse=True)
def rastro_somente_local():
    """Teste comum não usa rede, mesmo com `LANGFUSE_*` definido no shell."""
    auditoria.configurar_destino_externo(None)
    auditoria.RASTRO_LOCAL.limpar()
    yield
    auditoria.configurar_destino_externo(None)
    auditoria.RASTRO_LOCAL.limpar()


@pytest.fixture
def rastro(rastro_somente_local: None) -> CapturaRastro:
    """Todos os registros de rastro do teste, inclusive os que não têm contexto de empresa."""
    captura = CapturaRastro()
    auditoria.configurar_destino_externo(captura)
    return captura
