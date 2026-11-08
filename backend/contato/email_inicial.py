"""E-mail inicial do #50 (seção 9), que ajusta o convite da T3.1.

O modelo redige só o parágrafo de abertura, a partir dos fits da análise e sem
receber nome nem contato. O código monta o resto (convite para o WhatsApp com o
código curto, origem do contato, link de exclusão e aviso de simulação) e confere
o contato publicado e a lista de supressão antes de criar e de enviar.

`ContatoPublicado` e `EmailConvite` são tipos locais da frente até o modelo de
dados da seção 7 do #50 entrar em `backend/contratos` (#9).
"""

import base64
import hashlib
import logging
import re
from urllib.parse import quote

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from backend.contato.mensageiro import (
    _conferir_ids,
    _criterios_atendidos,
    _fits,
    chave_convite,
)
from backend.contato.prompts import (
    AVISO_SIMULACAO,
    MARCADOR_NOME,
    PALAVRA_SAIDA,
    SISTEMA_EMAIL,
    montar_pedido_email,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Convite, TipoConvite, Vaga

logger = logging.getLogger(__name__)

ETAPA_EMAIL = "redigir_email"
CANAL_EMAIL = "email"
TAMANHO_CODIGO = 6
LIMITE_PARAGRAFO = 1000
TENTATIVA_LEMBRETE = 2
_MARCADOR = re.compile(r"\{[^}]*\}")
_ENDERECO = re.compile(r"https?://|www\.|@")


class _Local(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContatoPublicado(_Local):
    """Contato que a própria pessoa publicou, com a origem (FR-031, FR-C020)."""

    canal: str
    endereco: str
    url_origem: str
    descricao_origem: str
    coletado_em: AwareDatetime
    publicado_para_contato: bool


class Remetente(_Local):
    """Quem envia: a empresa e o nosso número de WhatsApp."""

    nome_empresa: str
    numero_whatsapp: str

    @field_validator("numero_whatsapp")
    @classmethod
    def _so_digitos(cls, valor: str) -> str:
        if not valor.isdigit():
            raise ValueError("o número do WhatsApp deve ter só dígitos, com DDI")
        return valor


class RedacaoEmail(BaseModel):
    """Saída esperada do modelo na etapa `redigir_email`."""

    paragrafo: str
    criterios_citados: list[str]


class EmailConvite(_Local):
    """E-mail pronto para envio. `convite.mensagem` é o corpo completo."""

    convite: Convite
    para: str
    assunto: str
    cabecalhos: dict[str, str]
    codigo: str
    link_whatsapp: str
    link_exclusao: str


class ContatoBloqueado(Exception):
    """O contato não pode ser feito. `regra` diz qual regra bloqueou."""

    def __init__(self, regra: str) -> None:
        super().__init__(regra)
        self.regra = regra


def codigo_convite(empresa_id: str, vaga_id: str, candidato_id: str) -> str:
    """Código curto que liga a conversa do WhatsApp ao convite, sem dados pessoais.

    É o mesmo para o e-mail e o lembrete da mesma pessoa e vaga.
    """
    resumo = hashlib.sha256(f"{empresa_id}\x00{vaga_id}\x00{candidato_id}".encode()).digest()
    return base64.b32encode(resumo).decode()[:TAMANHO_CODIGO]


def _link_whatsapp(numero: str, codigo: str) -> str:
    return f"https://wa.me/{numero}?text={quote(f'Vaga {codigo}')}"


def _conferir_contato(empresa_id: str, contato: ContatoPublicado, lista: ListaSupressao) -> None:
    if contato.canal != CANAL_EMAIL:
        raise ContatoBloqueado("canal_nao_e_email")
    if not contato.publicado_para_contato or not contato.url_origem.strip():
        raise ContatoBloqueado("contato_nao_publicado")
    if lista.esta_suprimido(empresa_id, [contato.endereco]):
        raise ContatoBloqueado("lista_supressao")


def paragrafo_padrao(vaga: Vaga, analise: Analise, nome_empresa: str) -> str:
    """Abertura determinística, usada sem personalização ou quando o modelo falha."""
    criterios = ", ".join(_criterios_atendidos(vaga, analise))
    motivo = f" Seu perfil chamou nossa atenção por: {criterios}." if criterios else ""
    return f"Olá, {MARCADOR_NOME}! A {nome_empresa} tem uma vaga de {vaga.titulo}.{motivo}"


def paragrafo_lembrete(vaga: Vaga, nome_empresa: str) -> str:
    """Abertura do lembrete (T3.7): curta, fixa e sem modelo."""
    return (
        f"Olá, {MARCADOR_NOME}! Passando para lembrar da vaga de {vaga.titulo} na "
        f"{nome_empresa}. Este é o único lembrete."
    )


def _problema_na_redacao(
    redacao: RedacaoEmail, vaga: Vaga, fits: list[tuple[str, str]]
) -> str | None:
    texto = redacao.paragrafo
    if not texto.strip() or len(texto) > LIMITE_PARAGRAFO:
        return "vazia ou longa demais"
    if vaga.titulo.lower() not in texto.lower():
        return "sem o título da vaga"
    if _ENDERECO.search(texto.lower()):
        return "com endereço escrito pelo modelo"
    if set(_MARCADOR.findall(texto)) - {MARCADOR_NOME}:
        return "com marcador desconhecido"
    if not set(redacao.criterios_citados) <= {criterio for criterio, _ in fits}:
        return "citando critério sem evidência"
    return None


def _redigir(
    vaga: Vaga, nome_empresa: str, fits: list[tuple[str, str]], cliente_modelo: ClienteModelo
) -> str | None:
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_EMAIL, montar_pedido_email(vaga, nome_empresa, fits), RedacaoEmail, ETAPA_EMAIL
        )
        redacao = RedacaoEmail.model_validate(resposta.model_dump())
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("e-mail da vaga %s usou a abertura padrão: %s", vaga.id, erro)
        return None
    problema = _problema_na_redacao(redacao, vaga, fits)
    if problema:
        logger.warning("e-mail da vaga %s usou a abertura padrão: redação %s", vaga.id, problema)
        return None
    return redacao.paragrafo.strip()


def _corpo(
    abertura: str,
    remetente: Remetente,
    contato: ContatoPublicado,
    codigo: str,
    link_whatsapp: str,
    link_exclusao: str,
) -> str:
    data = contato.coletado_em.strftime("%d/%m/%Y")
    return "\n\n".join(
        [
            abertura,
            f"Se tiver interesse, fale com a gente pelo WhatsApp: {link_whatsapp}\n"
            f"A mensagem já vem com o código {codigo}, que liga a conversa a este convite.",
            f"Por que você recebeu este e-mail: a {remetente.nome_empresa} encontrou este "
            f"endereço em {contato.descricao_origem} ({contato.url_origem}), em {data}. "
            "Guardamos só dados profissionais públicos, para falar sobre esta vaga.",
            "Para não receber mais contatos e apagar seus dados, use este link: "
            f"{link_exclusao}\nVocê também pode responder {PALAVRA_SAIDA}.",
            AVISO_SIMULACAO,
        ]
    )


def criar_email(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    contato: ContatoPublicado,
    remetente: Remetente,
    lista: ListaSupressao,
    cliente_modelo: ClienteModelo,
    *,
    personalizar: bool = True,
    tentativa: int = 1,
) -> EmailConvite:
    """Monta o e-mail inicial ou, com `tentativa=2`, o único lembrete (T3.7).

    Lança `ContatoBloqueado` quando o contato não foi publicado pela pessoa, não é
    e-mail ou está na lista de supressão. `pode_contatar` continua com o fluxo (T1.1).
    """
    if tentativa not in (1, TENTATIVA_LEMBRETE):
        raise ValueError("há só o e-mail inicial e um lembrete por vaga")
    _conferir_ids(vaga, candidato, analise)
    _conferir_contato(vaga.empresa_id, contato, lista)
    lembrete = tentativa == TENTATIVA_LEMBRETE

    abertura = paragrafo_lembrete(vaga, remetente.nome_empresa) if lembrete else None
    if abertura is None and personalizar:
        fits = _fits(analise, candidato.nome)
        abertura = _redigir(vaga, remetente.nome_empresa, fits, cliente_modelo)
    if abertura is None:
        abertura = paragrafo_padrao(vaga, analise, remetente.nome_empresa)
    abertura = abertura.replace(MARCADOR_NOME, candidato.nome)

    codigo = codigo_convite(vaga.empresa_id, vaga.id, candidato.id)
    link_whatsapp = _link_whatsapp(remetente.numero_whatsapp, codigo)
    link_exclusao = lista.link_exclusao(vaga.empresa_id, candidato.id, [contato.endereco])
    corpo = _corpo(abertura, remetente, contato, codigo, link_whatsapp, link_exclusao)

    chave = chave_convite(vaga.empresa_id, vaga.id, candidato.id, TipoConvite.VAGA, tentativa)
    convite = Convite(
        id=chave,
        empresa_id=vaga.empresa_id,
        tipo=TipoConvite.VAGA,
        canal=CANAL_EMAIL,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        mensagem=corpo,
        link_agendamento=None,
        chave_idempotencia=chave,
        simulado=True,
    )
    return EmailConvite(
        convite=convite,
        para=contato.endereco,
        assunto=f"[SIMULADO] {'Lembrete: vaga' if lembrete else 'Vaga'} de {vaga.titulo} "
        f"na {remetente.nome_empresa}",
        cabecalhos=ListaSupressao.cabecalhos_exclusao(link_exclusao),
        codigo=codigo,
        link_whatsapp=link_whatsapp,
        link_exclusao=link_exclusao,
    )


class MensageiroEmailSimulado:
    """Provedor de e-mail simulado: caixa por empresa, idempotente por chave.

    Consulta a lista de supressão de novo na hora do envio, porque a pessoa pode
    ter saído depois de o e-mail ser montado.
    """

    def __init__(self, lista: ListaSupressao, falhas_restantes: int = 0) -> None:
        self.lista = lista
        self.falhas_restantes = falhas_restantes
        self._caixas: dict[str, dict[str, EmailConvite]] = {}
        self._por_codigo: dict[str, EmailConvite] = {}

    def _caixa(self, empresa_id: str) -> dict[str, EmailConvite]:
        if not empresa_id or not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório em toda leitura e escrita")
        return self._caixas.setdefault(empresa_id, {})

    def enviar(self, email: EmailConvite) -> bool:
        convite = email.convite
        if not convite.simulado:
            raise ValueError("não há canal real: o mensageiro só envia e-mails simulados")
        caixa = self._caixa(convite.empresa_id)
        if convite.chave_idempotencia in caixa:
            return True
        if self.lista.esta_suprimido(convite.empresa_id, [email.para]):
            logger.info("envio bloqueado pela lista de supressão: %s", convite.id)
            raise ContatoBloqueado("lista_supressao")
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            return False
        caixa[convite.chave_idempotencia] = email
        self._por_codigo[email.codigo] = email
        return True

    def enviados(self, empresa_id: str) -> list[EmailConvite]:
        return list(self._caixa(empresa_id).values())

    def por_codigo(self, codigo: str) -> EmailConvite | None:
        """E-mail mais recente com o código, para ligar a conversa do WhatsApp (T3.9)."""
        return self._por_codigo.get(codigo.strip().upper())
