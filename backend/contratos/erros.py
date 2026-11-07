"""Erros compartilhados entre as frentes."""


class ErroContrato(Exception):
    """Base dos erros previsíveis do projeto."""


class FonteIndisponivel(ErroContrato):
    """Fonte de candidatos fora do ar ou com limite atingido."""


class ModeloIndisponivel(ErroContrato):
    """Modelo de IA indisponível depois das tentativas e alternativas."""


class RespostaInvalida(ErroContrato):
    """Resposta do modelo fora do esquema esperado."""


class LimiteGastoAtingido(ErroContrato):
    """Limite de gasto da sessão atingido; o fluxo deve pausar com estado salvo."""
