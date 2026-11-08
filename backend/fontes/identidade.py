"""Resolução de identidade: junta registros da mesma pessoa vindos de fontes diferentes.

Etapa "Resolver identidade" do pipeline de coleta, em código puro: sem rede, sem modelo,
sem estado e sem efeito colateral. A entrada já está na memória.

Só sinal forte une: o mesmo e-mail, a mesma URL de perfil ou o mesmo par de host e usuário
numa plataforma em que o primeiro segmento do caminho é o usuário (`PLATAFORMAS_DE_USUARIO`).
Em qualquer outro site, o primeiro segmento é uma seção (`sites.google.com/view`,
`ufpe.br/docentes`), e só a URL inteira une. Nome e cidade parecidos nunca unem; viram
sugestão para uma pessoa decidir. Na dúvida, os registros ficam separados.

URL do LinkedIn não serve de chave: o coletor recusa esses domínios por completo
(`DOMINIOS_LINKEDIN` e `_LINK_PROIBIDO` em `backend/fontes/provedores/url_segura.py`), então
um registro descoberto pelo índice de busca só se junta a outro por e-mail, site ou GitHub.

`escopo` isola cada empresa: registros de escopos diferentes nunca se juntam nem viram
sugestão, mesmo com o mesmo e-mail.

`perfis` são URLs de perfil da pessoa (site pessoal, GitHub, GitLab, ORCID). A raiz de uma
plataforma, sem usuário, não identifica ninguém e não deveria chegar aqui.

O adaptador de `ItemColetado`, o modelo dos provedores externos, entra depois: ele monta
`SinaisIdentidade` e chama a mesma `resolver`, sem mexer no algoritmo.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.contratos.modelos import Candidato

DOMINIOS_LINKEDIN = ("linkedin.com", "linkedin.cn", "linked.in", "licdn.com", "lnkd.in")
"""Mesma lista do coletor. Repetida aqui porque a política do LinkedIn não pode depender
de um módulo de provedor estar instalado."""

ESQUEMAS_DE_PERFIL = frozenset({"http", "https"})
PLATAFORMAS_DE_USUARIO = frozenset(
    {
        "behance.net",
        "bitbucket.org",
        "codeberg.org",
        "dev.to",
        "dribbble.com",
        "github.com",
        "gitlab.com",
        "huggingface.co",
        "kaggle.com",
        "medium.com",
        "orcid.org",
    }
)
"""Hosts em que `host/primeiro_segmento` é a pessoa. Lista fechada: na dúvida, separado."""
SEGMENTOS_RESERVADOS = frozenset(
    {"about", "explore", "orgs", "p", "settings", "sponsors", "tag", "tags", "topics", "users"}
)
"""Primeiros segmentos que são páginas da plataforma, não usuários."""
CAMPOS_DE_PERFIL = ("links", "perfis")
CAMPOS_DE_LOCAL = ("cidade", "local")

_LINKEDIN = re.compile("|".join(re.escape(d) for d in (*DOMINIOS_LINKEDIN, "linkedin")), re.I)


@dataclass(frozen=True, slots=True)
class SinaisIdentidade:
    """Sinais de um registro, independentes de contrato.

    `registro_id` identifica o registro, não a pessoa: a mesma pessoa vinda de três fontes
    chega como três registros. `escopo` vazio significa um conjunto só.
    """

    registro_id: str
    fonte: str
    emails: frozenset[str] = frozenset()
    perfis: frozenset[str] = frozenset()
    nome: str = ""
    local: str = ""
    escopo: str = ""


@dataclass(frozen=True, slots=True)
class Grupo:
    """Registros tidos como a mesma pessoa.

    `id_grupo` é o menor `registro_id` do grupo, prefixado pelo escopo quando há escopo.
    `chaves_fortes` traz só as chaves compartilhadas por mais de um registro, que são as
    que de fato causaram a junção.
    """

    id_grupo: str
    registros: tuple[str, ...]
    chaves_fortes: tuple[str, ...]
    conflito_de_nome: bool


@dataclass(frozen=True, slots=True)
class Sugestao:
    """Par de grupos parecido por nome e local que não foi unido, para revisão humana."""

    id_grupo_a: str
    id_grupo_b: str
    motivo: str


@dataclass(frozen=True, slots=True)
class Resolucao:
    grupos: tuple[Grupo, ...]
    sugestoes: tuple[Sugestao, ...]


def normalizar_email(valor: str) -> str | None:
    """Minúsculas e sem espaço nas pontas.

    Sem truque de provedor: ponto e sufixo depois de `+` continuam valendo, porque tratá-los
    como iguais seria inferir identidade. Devolve `None` para o que não é endereço.
    """
    email = valor.strip().casefold()
    usuario, arroba, dominio = email.partition("@")
    if not arroba or not usuario or not dominio or "@" in dominio:
        return None
    return None if any(c.isspace() for c in email) else email


def normalizar_perfil(valor: str) -> str | None:
    """`host/caminho`: host em minúsculas, sem `www.`, sem barra final, consulta nem fragmento.

    Devolve `None` para o que não serve de chave: vazio, esquema que não é web e LinkedIn.
    """
    texto = valor.strip()
    if not texto or _LINKEDIN.search(texto):
        return None
    try:
        partes = urlsplit(texto if "://" in texto else f"https://{texto}")
        host = (partes.hostname or "").rstrip(".").casefold()
    except ValueError:
        return None
    if partes.scheme.casefold() not in ESQUEMAS_DE_PERFIL or not host:
        return None
    return f"{host.removeprefix('www.')}{partes.path.rstrip('/')}"


def sinais_de_candidato(candidato: Candidato) -> SinaisIdentidade:
    """Sinais de um `Candidato` do banco de talentos.

    O registro é o par de `id` e `fonte`: o mesmo perfil importado de duas fontes são dois
    registros, e juntá-los é trabalho da `resolver`. `links` e `perfis` podem trazer vários
    valores separados por vírgula.
    """
    atributos = candidato.atributos
    return SinaisIdentidade(
        registro_id=f"{candidato.id}:{candidato.fonte}",
        fonte=candidato.fonte,
        emails=_separados(atributos.get("email", "")),
        perfis=frozenset().union(*(_separados(atributos.get(c, "")) for c in CAMPOS_DE_PERFIL)),
        nome=candidato.nome,
        local=next((atributos[c] for c in CAMPOS_DE_LOCAL if atributos.get(c)), ""),
        escopo=candidato.empresa_id,
    )


def resolver(sinais: Sequence[SinaisIdentidade]) -> Resolucao:
    """Agrupa os registros por sinal forte e sugere os pares que só se parecem.

    O resultado não depende da ordem da entrada: os ids vêm do conteúdo, não de contador.
    """
    chaves_por_registro = {}
    for sinal in sinais:
        no = (sinal.escopo, sinal.registro_id)
        if not sinal.registro_id.strip():
            raise ValueError("registro_id é obrigatório")
        if no in chaves_por_registro:
            raise ValueError(f"registro_id repetido no mesmo escopo: {sinal.registro_id!r}")
        chaves_por_registro[no] = _chaves_fortes(sinal)

    uniao = _UniaoBusca()
    por_chave: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for no, chaves in chaves_por_registro.items():
        uniao.adicionar(no)
        for chave in chaves:
            por_chave.setdefault((no[0], chave), []).append(no)
    for companheiros in por_chave.values():
        for outro in companheiros[1:]:
            uniao.unir(companheiros[0], outro)

    componentes: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for no in chaves_por_registro:
        componentes.setdefault(uniao.raiz(no), []).append(no)

    sinais_por_no = {(s.escopo, s.registro_id): s for s in sinais}
    grupos, nos_por_grupo = [], {}
    for nos in componentes.values():
        ordenados = sorted(nos)
        grupo = _montar_grupo(ordenados, chaves_por_registro, sinais_por_no)
        grupos.append(grupo)
        nos_por_grupo[grupo.id_grupo] = ordenados
    grupos.sort(key=lambda grupo: grupo.id_grupo)
    return Resolucao(
        grupos=tuple(grupos), sugestoes=_sugerir(grupos, nos_por_grupo, sinais_por_no)
    )


class _UniaoBusca:
    """União-busca com compressão de caminho. A partição final não depende da ordem."""

    def __init__(self) -> None:
        self._pai: dict[tuple[str, str], tuple[str, str]] = {}

    def adicionar(self, no: tuple[str, str]) -> None:
        self._pai.setdefault(no, no)

    def raiz(self, no: tuple[str, str]) -> tuple[str, str]:
        while self._pai[no] != no:
            self._pai[no] = self._pai[self._pai[no]]
            no = self._pai[no]
        return no

    def unir(self, um: tuple[str, str], outro: tuple[str, str]) -> None:
        raiz_um, raiz_outro = self.raiz(um), self.raiz(outro)
        if raiz_um != raiz_outro:
            self._pai[max(raiz_um, raiz_outro)] = min(raiz_um, raiz_outro)


def _separados(texto: str) -> frozenset[str]:
    return frozenset(parte.strip() for parte in texto.split(",") if parte.strip())


def _chaves_fortes(sinal: SinaisIdentidade) -> frozenset[str]:
    chaves = {f"email:{e}" for e in map(normalizar_email, sinal.emails) if e}
    for perfil in (normalizar_perfil(p) for p in sinal.perfis):
        if perfil is None:
            continue
        chaves.add(f"perfil:{perfil}")
        host, barra, caminho = perfil.partition("/")
        usuario = caminho.split("/")[0]
        if (
            barra
            and usuario
            and host in PLATAFORMAS_DE_USUARIO
            and usuario.casefold() not in SEGMENTOS_RESERVADOS
        ):
            chaves.add(f"perfil:{host}/{usuario}")
    return frozenset(chaves)


def _montar_grupo(
    nos: list[tuple[str, str]],
    chaves_por_registro: dict[tuple[str, str], frozenset[str]],
    sinais_por_no: dict[tuple[str, str], SinaisIdentidade],
) -> Grupo:
    escopo = nos[0][0]
    registros = tuple(registro_id for _, registro_id in nos)
    contagem: dict[str, int] = {}
    for no in nos:
        for chave in chaves_por_registro[no]:
            contagem[chave] = contagem.get(chave, 0) + 1
    nomes = [sinais_por_no[no].nome for no in nos]
    return Grupo(
        id_grupo=f"{escopo}:{registros[0]}" if escopo else registros[0],
        registros=registros,
        chaves_fortes=tuple(sorted(c for c, vezes in contagem.items() if vezes > 1)),
        conflito_de_nome=_ha_conflito(nomes),
    )


def _sugerir(
    grupos: Sequence[Grupo],
    nos_por_grupo: dict[str, list[tuple[str, str]]],
    sinais_por_no: dict[tuple[str, str], SinaisIdentidade],
) -> tuple[Sugestao, ...]:
    """Pares de grupos parecidos por nome e local. Parecer não une, só pede uma decisão."""
    por_grupo = {
        id_grupo: [sinais_por_no[no] for no in nos] for id_grupo, nos in nos_por_grupo.items()
    }
    sugestoes = []
    for indice, grupo in enumerate(grupos):
        for outro in grupos[indice + 1 :]:
            parecido = _par_parecido(por_grupo[grupo.id_grupo], por_grupo[outro.id_grupo])
            if parecido is not None:
                um, dois = parecido
                sugestoes.append(
                    Sugestao(
                        id_grupo_a=grupo.id_grupo,
                        id_grupo_b=outro.id_grupo,
                        motivo=(
                            f"nome e local parecidos, sem sinal forte: "
                            f"{um.nome!r} em {um.local!r} e {dois.nome!r} em {dois.local!r}"
                        ),
                    )
                )
    return tuple(sugestoes)


def _par_parecido(
    uns: Sequence[SinaisIdentidade], outros: Sequence[SinaisIdentidade]
) -> tuple[SinaisIdentidade, SinaisIdentidade] | None:
    if uns[0].escopo != outros[0].escopo:
        return None
    for um in uns:
        for dois in outros:
            if _parecidos(um.nome, dois.nome) and _parecidos(um.local, dois.local):
                return um, dois
    return None


def _ha_conflito(nomes: Iterable[str]) -> bool:
    preenchidos = [nome for nome in nomes if _palavras(nome)]
    return any(
        not _parecidos(um, dois)
        for indice, um in enumerate(preenchidos)
        for dois in preenchidos[indice + 1 :]
    )


def _parecidos(um: str, outro: str) -> bool:
    """Um conjunto de palavras contido no outro. Texto vazio não se parece com nada."""
    palavras_um, palavras_outro = _palavras(um), _palavras(outro)
    if not palavras_um or not palavras_outro:
        return False
    return palavras_um <= palavras_outro or palavras_outro <= palavras_um


def _palavras(texto: str) -> frozenset[str]:
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    letras = "".join(c if c.isalnum() else " " for c in sem_acento if not unicodedata.combining(c))
    return frozenset(letras.split())
