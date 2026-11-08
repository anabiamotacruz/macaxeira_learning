"""Estado "sem canal" e fila de abordagem manual (spec 002, história 1, cenário 2).

Candidato bom sem e-mail publicado não pode virar exceção perdida: ele vira item de
trabalho para o recrutador, que aborda pelo LinkedIn dele, pela conta dele (#50,
seção 4, camada 3). Aqui nada é enviado, nenhum endereço é inferido e nenhum texto
passa por modelo de IA: a mensagem sugerida é a mesma abertura determinística do
e-mail inicial.

Quem pediu para sair não entra na fila. Abordar por outro canal continua sendo
abordar, então a lista de supressão e o opt-out vencem o estado "sem canal".
"""

import logging
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime

from backend.contato.conversa import contem_instrucao
from backend.contato.email_inicial import (
    ContatoBloqueado,
    ContatoPublicado,
    EmailConvite,
    Remetente,
    criar_email,
    paragrafo_padrao,
)
from backend.contato.mensageiro import _conferir_ids, _criterios_atendidos
from backend.contato.pacote import CRITERIOS_SENSIVEIS, _normalizar
from backend.contato.prompts import MARCADOR_NOME
from backend.contato.supressao import ListaSupressao
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Contrato, Texto, Vaga

logger = logging.getLogger(__name__)

ENVIO_MANUAL = (
    "Envie você mesmo, pela sua conta do LinkedIn, copiando o texto sugerido. "
    "O sistema não envia esta mensagem e não automatiza nada dentro do LinkedIn."
)
ALERTA_INSTRUCAO = "perfil com texto dirigido ao avaliador, tratado como dado e não como instrução"


class MotivoSemCanal(StrEnum):
    """Por que a pessoa ficou sem canal de contato.

    Os valores seguem a `regra` de `ContatoBloqueado`, menos `CONTATO_SEM_ORIGEM`: o
    portão aplica `contato_nao_publicado` também ao endereço sem URL de origem, e a
    fila separa os dois casos para quem a lê.
    """

    SEM_CONTATO_PUBLICADO = "contato_nao_publicado"
    CONTATO_SEM_ORIGEM = "contato_sem_origem"
    CANAL_NAO_SUPORTADO = "canal_nao_e_email"
    LISTA_SUPRESSAO = "lista_supressao"


class ItemAbordagemManual(Contrato):
    """Trabalho para o recrutador: a mensagem pronta, sem contato e sem link.

    O item não guarda e-mail, telefone nem endereço, porque não há contato
    publicado para guardar. O envio é sempre da pessoa do RH.
    """

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    motivo: MotivoSemCanal
    criterios_atendidos: list[str]
    texto_sugerido: str
    instrucao_envio: str = ENVIO_MANUAL
    alertas: list[str] = []
    criado_em: AwareDatetime
    simulado: bool


def _e_sensivel(criterio: str) -> bool:
    """Critério que cita atributo sensível, por palavra inteira."""
    palavras = _normalizar(criterio).split("_")
    for sensivel in CRITERIOS_SENSIVEIS:
        termos = sensivel.split("_")
        janelas = range(len(palavras) - len(termos) + 1)
        if any(palavras[i : i + len(termos)] == termos for i in janelas):
            return True
    return False


def _sem_criterio_sensivel(vaga: Vaga, analise: Analise) -> Analise:
    """Barreira de defesa: a T1.1 já recusa critério sensível na vaga."""
    descricoes = {r.id: r.descricao for r in vaga.requisitos}
    return analise.model_copy(
        update={
            "evidencias": [e for e in analise.evidencias if not _e_sensivel(e.criterio)],
            "requisitos_ok": {
                rid: ok and not _e_sensivel(descricoes.get(rid, rid))
                for rid, ok in analise.requisitos_ok.items()
            },
        }
    )


def _alertas(candidato: Candidato, analise: Analise) -> list[str]:
    textos = [candidato.perfil_texto, *(e.trecho for e in analise.evidencias)]
    if not any(contem_instrucao(texto) for texto in textos):
        return []
    logger.warning(
        "alerta: instrução no perfil do candidato %s na vaga %s", candidato.id, analise.vaga_id
    )
    return [ALERTA_INSTRUCAO]


def preparar_abordagem(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    *,
    nome_empresa: str,
    motivo: MotivoSemCanal,
    criado_em: datetime,
) -> ItemAbordagemManual:
    """Monta o item da fila, com texto determinístico e sem modelo de IA."""
    _conferir_ids(vaga, candidato, analise)
    if motivo == MotivoSemCanal.LISTA_SUPRESSAO:
        raise ValueError("quem está na lista de supressão não entra na fila de abordagem manual")
    if candidato.opt_out:
        raise ValueError("quem pediu para sair não entra na fila de abordagem manual")

    limpa = _sem_criterio_sensivel(vaga, analise)
    abertura = paragrafo_padrao(vaga, limpa, nome_empresa).replace(MARCADOR_NOME, candidato.nome)
    partes = [
        abertura,
        "Se fizer sentido, me responda por aqui e a gente conversa. Se preferir não receber "
        "contatos, basta dizer, e a gente respeita.",
    ]
    if candidato.simulado:
        partes.append("Mensagem simulada, preparada em ambiente de demonstração.")

    return ItemAbordagemManual(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        motivo=motivo,
        criterios_atendidos=_criterios_atendidos(vaga, limpa),
        texto_sugerido="\n\n".join(partes),
        instrucao_envio=ENVIO_MANUAL,
        alertas=_alertas(candidato, analise),
        criado_em=criado_em,
        simulado=candidato.simulado,
    )


class FilaAbordagemManual:
    """Fila "abordar pelo LinkedIn" em memória, isolada por empresa.

    Idempotente por empresa, vaga e candidato: registrar de novo devolve o item que
    já estava na fila, sem duplicar nem mudar `criado_em`.
    """

    def __init__(self) -> None:
        self._filas: dict[str, dict[tuple[str, str], ItemAbordagemManual]] = {}

    def _da_empresa(self, empresa_id: str) -> dict[tuple[str, str], ItemAbordagemManual]:
        if not empresa_id or not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório em toda leitura e escrita")
        return self._filas.setdefault(empresa_id, {})

    def registrar(self, item: ItemAbordagemManual) -> ItemAbordagemManual:
        fila = self._da_empresa(item.empresa_id)
        guardado = fila.setdefault((item.vaga_id, item.candidato_id), item)
        if guardado is item:
            logger.info(
                "sem canal: empresa=%s vaga=%s candidato=%s motivo=%s",
                item.empresa_id,
                item.vaga_id,
                item.candidato_id,
                item.motivo.value,
            )
        return guardado

    def listar(self, empresa_id: str, vaga_id: str | None = None) -> list[ItemAbordagemManual]:
        """Itens da empresa, ordenados por vaga e candidato para a ordem não variar."""
        fila = self._da_empresa(empresa_id)
        chaves = sorted(fila) if vaga_id is None else sorted(k for k in fila if k[0] == vaga_id)
        return [fila[chave] for chave in chaves]

    def remover(self, empresa_id: str, vaga_id: str, candidato_id: str) -> bool:
        """Tira o item da fila, por exemplo quando o recrutador já abordou a pessoa."""
        return self._da_empresa(empresa_id).pop((vaga_id, candidato_id), None) is not None


class Caminho(StrEnum):
    """O que aconteceu ao tentar o contato, para o chamador não adivinhar."""

    EMAIL = "email"
    """Havia contato publicado: o e-mail foi montado e nada entrou na fila."""

    SEM_CANAL = "sem_canal"
    """Não havia contato publicado: a pessoa virou item de abordagem manual."""

    BLOQUEADO = "bloqueado"
    """Pediu para sair ou está na lista de supressão: não entra na fila e não recebe e-mail."""


class ResultadoEncaminhamento(Contrato):
    """Um dos dois caminhos, ou o bloqueio. Nunca os dois ao mesmo tempo."""

    caminho: Caminho
    email: EmailConvite | None = None
    item: ItemAbordagemManual | None = None
    motivo: MotivoSemCanal | None = None


def _motivo_do_bloqueio(contato: ContatoPublicado, regra: str) -> MotivoSemCanal:
    """Traduz a regra de `ContatoBloqueado` no motivo da fila.

    Endereço sem URL de origem e endereço que a pessoa não publicou caem na mesma
    regra do portão. Aqui eles ficam distinguíveis para quem lê a fila.
    """
    if regra == MotivoSemCanal.CANAL_NAO_SUPORTADO.value:
        return MotivoSemCanal.CANAL_NAO_SUPORTADO
    if regra == MotivoSemCanal.LISTA_SUPRESSAO.value:
        return MotivoSemCanal.LISTA_SUPRESSAO
    if not contato.url_origem.strip():
        return MotivoSemCanal.CONTATO_SEM_ORIGEM
    return MotivoSemCanal.SEM_CONTATO_PUBLICADO


def encaminhar_para_humano(
    *,
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    contato: ContatoPublicado | None,
    remetente: Remetente,
    lista: ListaSupressao,
    cliente_modelo: ClienteModelo,
    fila: FilaAbordagemManual,
    criado_em: datetime,
    identidades: list[str] | None = None,
) -> ResultadoEncaminhamento:
    """Tenta o e-mail e, sem contato publicado, registra a abordagem manual.

    Quem pediu para sair ou está na lista de supressão não entra na fila: abordar
    por outro canal continua sendo abordar. `identidades` são outros identificadores
    públicos da pessoa, como a URL do perfil, conferidos na lista mesmo sem contato
    publicado. O e-mail montado não é enviado daqui.
    """
    conferir = list(identidades or [])
    if contato is not None:
        conferir.append(contato.endereco)
    if candidato.opt_out or (conferir and lista.esta_suprimido(vaga.empresa_id, conferir)):
        return ResultadoEncaminhamento(
            caminho=Caminho.BLOQUEADO, motivo=MotivoSemCanal.LISTA_SUPRESSAO
        )

    if contato is not None:
        try:
            email = criar_email(
                vaga, candidato, analise, contato, remetente, lista, cliente_modelo
            )
        except ContatoBloqueado as erro:
            motivo = _motivo_do_bloqueio(contato, erro.regra)
            if motivo == MotivoSemCanal.LISTA_SUPRESSAO:
                return ResultadoEncaminhamento(caminho=Caminho.BLOQUEADO, motivo=motivo)
        else:
            return ResultadoEncaminhamento(caminho=Caminho.EMAIL, email=email)
    else:
        motivo = MotivoSemCanal.SEM_CONTATO_PUBLICADO

    item = fila.registrar(
        preparar_abordagem(
            vaga,
            candidato,
            analise,
            nome_empresa=remetente.nome_empresa,
            motivo=motivo,
            criado_em=criado_em,
        )
    )
    return ResultadoEncaminhamento(caminho=Caminho.SEM_CANAL, item=item, motivo=motivo)
