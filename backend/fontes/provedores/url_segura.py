"""Política das URLs externas: sem LinkedIn, sem encurtador e sem endereço interno.

As páginas são lidas pela Bright Data, não por este servidor. Mesmo assim a checagem roda aqui,
antes de pagar pela chamada, e cada redirecionamento passa de novo por ela.
"""

import ipaddress
import re
import socket
import unicodedata
from collections.abc import Callable
from urllib.parse import SplitResult, unquote, urlsplit

from backend.fontes.provedores.erros import MotivoTroca, UrlRecusada

TAMANHO_MAXIMO_URL = 2048
PORTAS_PERMITIDAS = frozenset({None, 80, 443})
ESQUEMAS_PERMITIDOS = frozenset({"http", "https"})
DOMINIOS_LINKEDIN = ("linkedin.com", "linkedin.cn", "linked.in", "licdn.com", "lnkd.in")
ENCURTADORES = (
    "bit.ly",
    "bl.ink",
    "buff.ly",
    "cutt.ly",
    "dub.sh",
    "goo.gl",
    "is.gd",
    "ow.ly",
    "rb.gy",
    "rebrand.ly",
    "short.io",
    "shorturl.at",
    "soo.gd",
    "t.co",
    "t.ly",
    "tiny.cc",
    "tinyurl.com",
    "trib.al",
)
"""Encurtador esconde o destino, que pode ser o LinkedIn: recusa sem tentar seguir."""
SUFIXOS_INTERNOS = (
    "localhost",
    "local",
    "internal",
    "intranet",
    "lan",
    "home",
    "corp",
    "test",
    "invalid",
    "onion",
)
_REDES_RECUSADAS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("64:ff9b::/96"),
)
_NUMERICO = re.compile(r"(?:0x[0-9a-f]*|[0-9]+)")
_LINK_PROIBIDO = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:linkedin\.com|linkedin\.cn|linked\.in|licdn\.com|lnkd\.in)"
    r"(?:/\S*)?",
    re.IGNORECASE,
)
_MARCA_LINK_REMOVIDO = "[link removido]"
_TEXTO_PEDE_LINKEDIN = re.compile(r"linkedin|lnkd\.in|licdn", re.IGNORECASE)
_DECODIFICACOES = 3

type Resolvedor = Callable[[str], list[str]]


def resolver_dns(host: str) -> list[str]:
    """Todos os endereços do nome, para recusar quando qualquer um deles for interno."""
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})


def _no_dominio(host: str, dominios: tuple[str, ...]) -> bool:
    return any(host == dominio or host.endswith(f".{dominio}") for dominio in dominios)


def _partes(url: object) -> tuple[SplitResult, str]:
    if not isinstance(url, str) or not url or len(url) > TAMANHO_MAXIMO_URL:
        raise UrlRecusada(MotivoTroca.URL_INVALIDA)
    if any(c.isspace() or ord(c) < 32 or c == "\\" for c in url):
        raise UrlRecusada(MotivoTroca.URL_INVALIDA)
    try:
        partes = urlsplit(unicodedata.normalize("NFKC", url))
        host = partes.hostname or ""
        partes.port  # noqa: B018 - porta malformada só levanta erro ao ser lida
        if "%" in host:
            raise ValueError("host codificado")
        host = host.encode("idna").decode("ascii").rstrip(".").casefold()
    except ValueError:
        raise UrlRecusada(MotivoTroca.URL_INVALIDA) from None
    if partes.scheme.casefold() not in ESQUEMAS_PERMITIDOS or not host:
        raise UrlRecusada(MotivoTroca.URL_INVALIDA)
    if partes.username is not None or partes.password is not None:
        raise UrlRecusada(MotivoTroca.URL_INVALIDA)
    if partes.port not in PORTAS_PERMITIDAS:
        raise UrlRecusada(MotivoTroca.URL_INVALIDA)
    return partes, host


def _tem_linkedin_embutido(partes: SplitResult) -> bool:
    """Procura no caminho e na consulta, como nos redirecionadores e arquivos de páginas."""
    texto = "?".join((partes.path, partes.query, partes.fragment))
    for _ in range(_DECODIFICACOES):
        texto = unquote(texto)
    return _LINK_PROIBIDO.search(texto) is not None


def _host_e_ip_ou_interno(host: str) -> bool:
    if ":" in host or _NUMERICO.fullmatch(host.rsplit(".", 1)[-1]):
        return True
    return "." not in host or _no_dominio(host, SUFIXOS_INTERNOS)


def validar_forma(url: str) -> str:
    """Recusa pela forma da URL, sem consultar DNS. Devolve a própria URL, se passar."""
    partes, host = _partes(url)
    if "linkedin" in host or _no_dominio(host, DOMINIOS_LINKEDIN + ENCURTADORES):
        raise UrlRecusada(MotivoTroca.DOMINIO_RECUSADO)
    if _tem_linkedin_embutido(partes):
        raise UrlRecusada(MotivoTroca.DOMINIO_RECUSADO)
    if _host_e_ip_ou_interno(host):
        raise UrlRecusada(MotivoTroca.ENDERECO_NAO_PUBLICO)
    return url


def validar_perfil(perfil: str) -> str:
    """Valida um perfil social, que muitas fontes escrevem sem esquema."""
    texto = perfil.strip()
    validar_forma(texto if "://" in texto else f"https://{texto}")
    return texto


def validar_texto_de_busca(texto: str) -> str:
    """Uma busca não pode pedir páginas do LinkedIn."""
    if _TEXTO_PEDE_LINKEDIN.search(texto):
        raise UrlRecusada(MotivoTroca.DOMINIO_RECUSADO)
    return texto


def _endereco_publico(endereco: str) -> bool:
    ip = ipaddress.ip_address(endereco)
    if ip.version == 6:
        embutido = ip.ipv4_mapped or ip.sixtofour
        if embutido is not None:
            return _endereco_publico(str(embutido))
    if any(ip in rede for rede in _REDES_RECUSADAS if rede.version == ip.version):
        return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def validar_url_publica(url: str, resolver: Resolvedor = resolver_dns) -> str:
    """Forma e DNS. Nome que não resolve, ou com algum endereço interno, é recusado."""
    validar_forma(url)
    _, host = _partes(url)
    try:
        enderecos = resolver(host)
        publicos = bool(enderecos) and all(_endereco_publico(e) for e in enderecos)
    except (OSError, ValueError):
        publicos = False
    if not publicos:
        raise UrlRecusada(MotivoTroca.ENDERECO_NAO_PUBLICO)
    return url


def remover_links_proibidos(texto: str) -> str:
    """Tira de texto externo os links do LinkedIn, para não chegarem ao banco nem ao modelo."""
    return _LINK_PROIBIDO.sub(_MARCA_LINK_REMOVIDO, texto)
