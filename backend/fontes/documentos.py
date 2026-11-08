"""Leitura de arquivos enviados pela própria pessoa (T2.9): texto, PDF e imagem com OCR.

Só recebe bytes já entregues como entrada: não abre caminho do disco nem busca nada na rede. PDF
exportado do LinkedIn entra apenas assim, enviado pela pessoa. Nenhuma afirmação fora do documento
entra no perfil, instrução vira alerta e o modelo só vê o texto pseudonimizado.
"""

import io
import re
import shutil
import warnings
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pypdfium2
import pytesseract
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from pypdf import PdfReader

from backend.agente.auditoria import rastreado
from backend.agente.prompts import como_dado
from backend.contratos.erros import ErroContrato, ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import (
    Candidato,
    ContatoColetado,
    FatoColetado,
    PerfilColetado,
    TipoContato,
    TipoFato,
)
from backend.fontes.analisador import normalizar, preparar_texto
from backend.fontes.anonimizador import (
    TERMOS_TECNICOS,
    Categoria,
    Identificadores,
    PerfilPseudonimizado,
    Pseudonimizador,
    encontrar_contatos,
    forma_canonica,
)
from backend.fontes.perfis import candidato_de_perfil, combina_com_consulta
from backend.fontes.prompts import SISTEMA_EXTRAIR_PERFIL, USUARIO_EXTRAIR_PERFIL

ETAPA_LER_DOCUMENTO = "ler_documento"
ETAPA_EXTRAIR_PERFIL = "extrair_perfil"
FONTE_DOCUMENTO = "documento_enviado"
MAX_BYTES_DOCUMENTO = 5 * 1024 * 1024
MAX_CARACTERES_DOCUMENTO = 200_000
MAX_PAGINAS_PDF = 30
MAX_PAGINAS_OCR = 10
MAX_PIXELS_IMAGEM = 40_000_000
TEMPO_MAXIMO_OCR_S = 30
RESOLUCAO_OCR_DPI = 200
IDIOMAS_OCR = ("por", "eng")

ALERTA_INSTRUCAO_DOCUMENTO = (
    "instrucao_no_documento: o documento traz texto dirigido ao avaliador; ele foi ignorado."
)

_ASSINATURAS: dict[str, Callable[[bytes], bool]] = {
    ".pdf": lambda c: c[:1024].lstrip().startswith(b"%PDF-"),
    ".png": lambda c: c.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda c: c.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda c: c.startswith(b"\xff\xd8\xff"),
    ".webp": lambda c: c[:4] == b"RIFF" and c[8:12] == b"WEBP",
    ".txt": lambda c: b"\x00" not in c,
    ".md": lambda c: b"\x00" not in c,
}
EXTENSOES_PERMITIDAS = frozenset(_ASSINATURAS)
_CABECALHO_DE_NOME = re.compile(r"^[^\W\d_]+(?:[ \t]+[^\W\d_]+){1,5}$")


class DocumentoInvalido(ErroContrato):
    """Tipo de arquivo não suportado, conteúdo diferente da extensão ou arquivo além do limite."""


class DocumentoIlegivel(ErroContrato):
    """PDF ou imagem sem texto legível, mesmo com OCR: pede novo envio à pessoa."""


class OcrIndisponivel(ErroContrato):
    """O arquivo precisa de OCR e o `tesseract` não está instalado no sistema."""


class RespostaExtracaoPerfil(BaseModel):
    cargo: str = ""
    experiencias: list[str] = Field(default_factory=list)
    competencias: list[str] = Field(default_factory=list)


def _exigir_tesseract() -> None:
    if shutil.which("tesseract") is None:
        raise OcrIndisponivel(
            "Este arquivo precisa de OCR, mas o tesseract não está instalado no sistema. "
            "Instale o tesseract ou peça um arquivo com texto."
        )


def _ocr(imagem: Image.Image) -> str:
    _exigir_tesseract()
    try:
        disponiveis = set(pytesseract.get_languages(config=""))
        idiomas = "+".join(i for i in IDIOMAS_OCR if i in disponiveis) or "eng"
        return pytesseract.image_to_string(imagem, lang=idiomas, timeout=TEMPO_MAXIMO_OCR_S)
    except pytesseract.TesseractNotFoundError as erro:
        raise OcrIndisponivel("O tesseract não está disponível para ler este arquivo.") from erro
    except (RuntimeError, OSError, pytesseract.TesseractError) as erro:
        raise DocumentoIlegivel("Não foi possível ler a imagem; peça um novo envio.") from erro


def _ler_imagem(conteudo: bytes, extensao: str) -> str:
    formatos = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            imagem = Image.open(io.BytesIO(conteudo), formats=[formatos[extensao]])
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as erro:
        raise DocumentoInvalido("A imagem passa do limite de tamanho.") from erro
    except (UnidentifiedImageError, OSError) as erro:
        raise DocumentoIlegivel("Não foi possível ler a imagem; peça um novo envio.") from erro
    largura, altura = imagem.size
    if largura * altura > MAX_PIXELS_IMAGEM:
        raise DocumentoInvalido("A imagem passa do limite de tamanho.")
    return _ocr(imagem)


def _texto_do_pdf(conteudo: bytes) -> str:
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        if leitor.is_encrypted:
            raise DocumentoIlegivel("O PDF está protegido por senha; peça um arquivo sem senha.")
        if len(leitor.pages) > MAX_PAGINAS_PDF:
            raise DocumentoInvalido(f"O PDF passa do limite de {MAX_PAGINAS_PDF} páginas.")
        partes = [(pagina.extract_text() or "").strip() for pagina in leitor.pages]
    except ErroContrato:
        raise
    except Exception as erro:  # arquivo não confiável: qualquer falha do leitor é arquivo ilegível
        raise DocumentoIlegivel("Não foi possível ler o PDF; peça um novo envio.") from erro
    return "\n".join(parte for parte in partes if parte)


def _ocr_do_pdf(conteudo: bytes) -> str:
    _exigir_tesseract()
    escala = RESOLUCAO_OCR_DPI / 72
    partes = []
    try:
        documento = pypdfium2.PdfDocument(conteudo)
    except pypdfium2.PdfiumError as erro:
        raise DocumentoIlegivel("Não foi possível ler o PDF; peça um novo envio.") from erro
    try:
        for indice in range(min(len(documento), MAX_PAGINAS_OCR)):
            pagina = documento[indice]
            largura, altura = pagina.get_size()
            if largura * altura * escala * escala > MAX_PIXELS_IMAGEM:
                raise DocumentoInvalido("Uma página do PDF passa do limite de tamanho.")
            partes.append(_ocr(pagina.render(scale=escala).to_pil()))
    finally:
        documento.close()
    return "\n".join(partes)


def _ler_pdf(conteudo: bytes) -> str:
    return _texto_do_pdf(conteudo) or _ocr_do_pdf(conteudo)


def _ler_texto(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


@rastreado(ETAPA_LER_DOCUMENTO)
def ler_documento(nome: str, conteudo: bytes) -> str:
    """Lê texto, PDF ou imagem recebidos como bytes e devolve o texto, dentro dos limites."""
    if len(conteudo) > MAX_BYTES_DOCUMENTO:
        raise DocumentoInvalido("O arquivo excede o limite de 5 MB.")
    extensao = Path(nome or "").suffix.casefold()
    if extensao not in EXTENSOES_PERMITIDAS:
        raise DocumentoInvalido(f"Tipo de arquivo não permitido: {extensao or 'sem extensão'}.")
    if not _ASSINATURAS[extensao](conteudo):
        raise DocumentoInvalido("O conteúdo do arquivo não combina com a extensão.")

    if extensao in (".txt", ".md"):
        texto = _ler_texto(conteudo)
    elif extensao == ".pdf":
        texto = _ler_pdf(conteudo)
    else:
        texto = _ler_imagem(conteudo, extensao)

    limpo = texto.strip()
    if not limpo:
        raise DocumentoIlegivel("O documento não tem texto legível; peça um novo envio.")
    if len(limpo) > MAX_CARACTERES_DOCUMENTO:
        raise DocumentoInvalido("O documento passa do limite de caracteres.")
    return limpo


def extrair_links_e_contatos(texto: str) -> dict[str, str]:
    """Separa e-mail, telefone, perfis e demais links escritos no texto. Só lê, nada é buscado."""
    resultado: dict[str, str] = {}
    links: list[str] = []
    for categoria, valor in encontrar_contatos(texto):
        if categoria is Categoria.EMAIL:
            resultado.setdefault("email", valor.casefold())
        elif categoria is Categoria.TELEFONE:
            resultado.setdefault("telefone", " ".join(valor.split()))
        else:
            url = valor if "://" in valor else f"https://{valor}"
            for rede in ("linkedin", "github"):
                if categoria is Categoria.PERFIL and f"{rede}.com" in url.casefold():
                    resultado.setdefault(rede, url)
            if url not in links:
                links.append(url)
    if links:
        resultado["links"] = ", ".join(links)
    return resultado


def _nome_do_cabecalho(texto: str) -> str:
    """Primeira linha com só palavras costuma ser o nome no currículo: conta como nome a tirar."""
    primeira = next((linha.strip() for linha in texto.splitlines() if linha.strip()), "")
    if not _CABECALHO_DE_NOME.match(primeira):
        return ""
    return "" if any(p in TERMOS_TECNICOS for p in normalizar(primeira).split()) else primeira


def _no_documento(perfil: PerfilPseudonimizado, citado: str) -> str | None:
    """O que o modelo citou, de volta ao texto original. Fora do documento, não existe."""
    na_fonte = perfil.na_fonte(citado.strip()) if citado.strip() else None
    return na_fonte.texto if na_fonte is not None else None


@rastreado(ETAPA_EXTRAIR_PERFIL)
def extrair_perfil(
    texto: str,
    cliente_modelo: ClienteModelo,
    *,
    nome: str = "",
    pseudonimizador: Pseudonimizador | None = None,
    empresa_id: str = "documento",
    candidato_id: str = "documento",
) -> dict[str, str]:
    """Extrai resumo, experiências, competências, links e contatos, sem inventar dados."""
    canonico = forma_canonica(texto)
    contatos = extrair_links_e_contatos(canonico)
    sessao = (pseudonimizador or Pseudonimizador()).sessao_de_texto(
        empresa_id,
        candidato_id,
        canonico,
        Identificadores(
            nomes=tuple(n for n in (nome, _nome_do_cabecalho(canonico)) if n),
            valores=_identificadores_de_contato(contatos),
        ),
    )
    preparado = preparar_texto(sessao)
    perfil = preparado.pseudonimizado
    frases = list(preparado.frases_originais)
    experiencias: list[str] = []
    competencias: list[str] = []
    cargo = ""
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_EXTRAIR_PERFIL,
            USUARIO_EXTRAIR_PERFIL.format(documento=como_dado(perfil.texto)),
            RespostaExtracaoPerfil,
            ETAPA_EXTRAIR_PERFIL,
        )
    except (RespostaInvalida, ModeloIndisponivel):
        experiencias = list(frases)
    else:
        cargo = _no_documento(perfil, resposta.cargo) or ""
        experiencias = [t for c in resposta.experiencias if (t := _no_documento(perfil, c))]
        competencias = [t for c in resposta.competencias if (t := _no_documento(perfil, c))]

    saida = {
        "cargo": cargo,
        "resumo": " ".join(frases),
        "experiencias": " | ".join(experiencias),
        "competencias": ", ".join(competencias),
        **contatos,
    }
    if preparado.tem_instrucao:
        saida["alerta"] = ALERTA_INSTRUCAO_DOCUMENTO
    return saida


def _identificadores_de_contato(contatos: dict[str, str]) -> tuple[tuple[Categoria, str], ...]:
    valores: list[tuple[Categoria, str]] = []
    if "email" in contatos:
        valores.append((Categoria.EMAIL, contatos["email"]))
    for rede in ("linkedin", "github"):
        if rede in contatos:
            valores.append((Categoria.PERFIL, contatos[rede]))
    return tuple(valores)


def perfil_de_documento(
    *,
    empresa_id: str,
    candidato_id: str,
    nome: str,
    nome_arquivo: str,
    conteudo: bytes,
    cliente_modelo: ClienteModelo,
    hoje: date,
    simulado: bool,
    enviado_pela_pessoa: bool,
    pseudonimizador: Pseudonimizador | None = None,
) -> PerfilColetado:
    """Perfil em JSON a partir do arquivo. Tudo é declarado: a pessoa escreveu o documento."""
    if enviado_pela_pessoa is not True:
        raise DocumentoInvalido("Só entra documento enviado pela própria pessoa.")
    texto = ler_documento(nome_arquivo, conteudo)
    extraido = extrair_perfil(
        texto,
        cliente_modelo,
        nome=nome,
        pseudonimizador=pseudonimizador,
        empresa_id=empresa_id,
        candidato_id=candidato_id,
    )
    origem = {"fonte": FONTE_DOCUMENTO, "documento": nome_arquivo, "coletado_em": hoje}
    fatos = [
        FatoColetado(**origem, texto=frase, trecho=frase, tipo=TipoFato.DECLARADO)
        for frase in _fatos_de(extraido)
    ]
    contatos = [
        ContatoColetado(
            **origem,
            tipo=_TIPO_POR_CATEGORIA[categoria],
            valor=valor,
            publicado_pela_pessoa=True,
        )
        for categoria, valor in encontrar_contatos(texto)
    ]
    return PerfilColetado(
        empresa_id=empresa_id,
        candidato_id=candidato_id,
        simulado=simulado,
        coletado_em=hoje,
        nome=nome,
        fatos=fatos,
        contatos=contatos,
        alertas=[extraido["alerta"]] if "alerta" in extraido else [],
    )


_TIPO_POR_CATEGORIA = {
    Categoria.EMAIL: TipoContato.EMAIL,
    Categoria.TELEFONE: TipoContato.TELEFONE,
    Categoria.PERFIL: TipoContato.PERFIL,
    Categoria.LINK: TipoContato.LINK,
}


def _fatos_de(extraido: dict[str, str]) -> list[str]:
    experiencias = [e for e in extraido["experiencias"].split(" | ") if e]
    return experiencias or ([extraido["resumo"]] if extraido["resumo"] else [])


def candidato_de_documento(
    *,
    autorizacao_valida_ate: date | None = None,
    **dados,
) -> Candidato:
    """`Candidato` a partir do arquivo. Sem autorização informada, a pessoa fica pendente.

    O histórico fica vazio: o documento não dá datas nem empresas confiáveis, e inventá-las iria
    contra a regra de só afirmar o que consta. As experiências seguem no texto do perfil.
    """
    perfil = perfil_de_documento(**dados)
    atributos = {}
    if perfil.alertas:
        atributos["alerta_documento"] = perfil.alertas[0]
    return candidato_de_perfil(
        perfil,
        origem=dados["nome_arquivo"],
        fonte=FONTE_DOCUMENTO,
        autorizacao_valida_ate=autorizacao_valida_ate,
        atributos=atributos,
    )


class FonteDocumentosEnviados:
    """Implementa `FonteCandidatos` para quem já enviou o próprio documento."""

    def __init__(self) -> None:
        self._candidatos: list[Candidato] = []

    def adicionar(self, candidato: Candidato) -> None:
        self._candidatos = [
            c
            for c in self._candidatos
            if (c.empresa_id, c.id) != (candidato.empresa_id, candidato.id)
        ]
        self._candidatos.append(candidato)

    def remover(self, empresa_id: str, candidato_id: str) -> None:
        self._candidatos = [
            c for c in self._candidatos if (c.empresa_id, c.id) != (empresa_id, candidato_id)
        ]

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if pagina > 1:
            return []
        return [
            c
            for c in self._candidatos
            if c.empresa_id == empresa_id and combina_com_consulta(c, normalizar(consulta))
        ]
