import pytest

from backend.agente import auditoria


@pytest.fixture(autouse=True)
def rastro_somente_local():
    """Teste comum não usa rede, mesmo com `LANGFUSE_*` definido no shell."""
    auditoria.configurar_destino_externo(None)
    auditoria.RASTRO_LOCAL.limpar()
    yield
    auditoria.configurar_destino_externo(None)
    auditoria.RASTRO_LOCAL.limpar()
