"""Motivos de troca e erros permanentes dos provedores.

A mensagem traz só o motivo: nunca URL, chave ou dado de pessoa.
"""

from enum import StrEnum

from backend.contratos.erros import ErroContrato, FonteIndisponivel


class MotivoTroca(StrEnum):
    """Por que um provedor não entregou o resultado. Valores seguros para rastro e métrica."""

    NAO_ENCONTRADO = "nao_encontrado"
    FALHA_TEMPORARIA = "falha_temporaria"
    DISJUNTOR_ABERTO = "disjuntor_aberto"
    AUTENTICACAO = "autenticacao"
    SEM_CREDITOS = "sem_creditos"
    RECUSADO_PELO_PROVEDOR = "recusado_pelo_provedor"
    RESPOSTA_INVALIDA = "resposta_invalida"
    RESPOSTA_GRANDE_DEMAIS = "resposta_grande_demais"
    CONFIGURACAO_INCOMPLETA = "configuracao_incompleta"
    CONSULTA_NAO_SUPORTADA = "consulta_nao_suportada"
    CONSULTA_INVALIDA = "consulta_invalida"
    ORCAMENTO_ESGOTADO = "orcamento_esgotado"
    DOMINIO_RECUSADO = "dominio_recusado"
    ENDERECO_NAO_PUBLICO = "endereco_nao_publico"
    URL_INVALIDA = "url_invalida"


class ErroProvedor(ErroContrato):
    """Falha que repetir não resolve. `custo_usd` traz o que já foi cobrado até a falha."""

    def __init__(self, motivo: MotivoTroca, custo_usd: float = 0.0) -> None:
        super().__init__(motivo.value)
        self.motivo = motivo
        self.custo_usd = custo_usd


class UrlRecusada(ErroProvedor):
    """A política não deixa ler esta URL. Interrompe a cadeia: nenhum provedor deve tentá-la."""


class ProvedoresIndisponiveis(FonteIndisponivel):
    """Nenhum provedor respondeu. O fluxo trata como fonte fora do ar: cobertura parcial."""

    def __init__(self, motivos: list[tuple[str, MotivoTroca]]) -> None:
        resumo = ", ".join(f"{nome}={motivo.value}" for nome, motivo in motivos)
        super().__init__(f"provedores indisponíveis: {resumo}")
        self.motivos = motivos
