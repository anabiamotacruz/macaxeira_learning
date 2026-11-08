"""O limitador do processo vira um sem espera real, para nenhum teste dormir de verdade."""

import pytest

from backend.fontes.provedores import envoapi


@pytest.fixture(autouse=True)
def _limitador_isolado(monkeypatch):
    limitador = envoapi.LimitadorDePedidos(1000, relogio=lambda: 0.0, dormir=lambda _s: None)
    monkeypatch.setattr(envoapi, "limitador_do_processo", lambda: limitador)


@pytest.fixture(autouse=True)
def _cache_de_perfis_limpo():
    """O cache de perfis é do processo: cada teste começa e termina com ele vazio."""
    from backend.fontes.provedores import linkedin_por_brave

    linkedin_por_brave.limpar_cache_de_perfis()
    yield
    linkedin_por_brave.limpar_cache_de_perfis()
