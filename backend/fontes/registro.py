"""Fontes de candidatos plugáveis: uma lista configurável, em que só entra o que for habilitado."""

import os
from collections.abc import Callable, Iterable, Mapping

from backend.contratos.erros import ErroContrato
from backend.contratos.interfaces import FonteCandidatos

VARIAVEL_FONTES = "FONTES_HABILITADAS"


class FonteDesconhecida(ErroContrato):
    """Configuração citou fonte fora do catálogo. Não vira silêncio: pode ser erro de digitação."""


def habilitadas_do_ambiente() -> list[str]:
    """Nomes separados por vírgula. Sem a variável, nenhuma fonte entra."""
    valor = os.environ.get(VARIAVEL_FONTES, "")
    return [nome.strip() for nome in valor.split(",") if nome.strip()]


def montar_fontes(
    catalogo: Mapping[str, Callable[[], FonteCandidatos]], habilitadas: Iterable[str] = ()
) -> list[FonteCandidatos]:
    """Cria só as fontes habilitadas, na ordem pedida. A lista segue para `DependenciasFluxo`."""
    nomes = list(dict.fromkeys(habilitadas))
    desconhecidas = [nome for nome in nomes if nome not in catalogo]
    if desconhecidas:
        raise FonteDesconhecida(f"fontes fora do catálogo: {', '.join(desconhecidas)}")
    fontes = []
    for nome in nomes:
        fonte = catalogo[nome]()
        if not isinstance(fonte, FonteCandidatos):
            raise TypeError(f"{nome} não implementa FonteCandidatos")
        fontes.append(fonte)
    return fontes
