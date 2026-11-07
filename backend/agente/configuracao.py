"""Proposta de configuração de uma vaga a partir da descrição.

O modelo só interpreta o texto. Identificador, empresa, aprovação e limite de contato
são definidos por este código, e a vaga proposta ainda precisa de assinatura humana.
Na dúvida, devolve uma pergunta: não inventa requisito nem deixa critério sensível entrar.
"""

import hashlib
import re

from pydantic import Field

from backend.agente import prompts
from backend.agente.regras import TERMOS_SENSIVEIS, _contem, _palavras, validar_criterios
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Competencia, Contrato, Requisito, Texto, Vaga

ETAPA_CONFIGURACAO = "configuracao"

MAX_TENTATIVAS_CONTATO = 2
"""Limite de contato fixado em código: nem a descrição nem o modelo o alteram."""

TAMANHO_MAXIMO_DESCRICAO = 20_000
TAMANHO_MAXIMO_TRECHO = 200

TERMOS_SENSIVEIS_TEXTO: tuple[tuple[str, ...], ...] = tuple(
    (termo,) if isinstance(termo, str) else termo
    for termo in (
        "brancas",
        "brancos",
        "casada",
        "casadas",
        "casado",
        "casados",
        "deficiencia",
        "feminina",
        "feminino",
        "gender",
        "gestante",
        "gestantes",
        "gravida",
        "gravidas",
        "homem",
        "homens",
        "jovem",
        "jovens",
        "masculina",
        "masculino",
        "mulher",
        "mulheres",
        "negra",
        "negras",
        "negro",
        "negros",
        "pcd",
        "religion",
        "solteira",
        "solteiras",
        "solteiro",
        "solteiros",
        ("boa", "aparencia"),
        ("marital", "status"),
    )
)
"""Palavras que indicam atributo sensível em texto livre, além de `regras.TERMOS_SENSIVEIS`."""

MARCADORES_DE_AVISO: tuple[tuple[str, ...], ...] = (
    ("bem", "vindas"),
    ("bem", "vindos"),
    ("diversidade",),
    ("encorajamos",),
    ("igualdade", "de", "oportunidades"),
    ("incentivamos",),
    ("inclusao",),
    ("inclusiva",),
    ("inclusivo",),
    ("independente", "de"),
    ("independentemente", "de"),
    ("nao", "discrimina"),
    ("nao", "discriminamos"),
    ("nao", "fazemos", "distincao"),
    ("oportunidades", "iguais"),
    ("sem", "discriminacao"),
    ("sem", "distincao"),
)
"""Expressões típicas de aviso de não discriminação."""

MARCADORES_DE_RESTRICAO = frozenset(
    {
        "abaixo",
        "acima",
        "apenas",
        "ate",
        "contudo",
        "entre",
        "exceto",
        "exclusiva",
        "exclusivamente",
        "exclusivo",
        "exige",
        "exigida",
        "exigido",
        "exigimos",
        "maxima",
        "maximo",
        "mas",
        "minima",
        "minimo",
        "necessaria",
        "necessario",
        "obrigatoria",
        "obrigatorio",
        "porem",
        "preferencia",
        "preferencialmente",
        "requisito",
        "so",
        "somente",
    }
)
"""Palavras que tiram da frase o caráter de aviso: ela passa a restringir quem pode concorrer."""


class PerguntaVaga(Contrato):
    """Dúvida devolvida à pessoa, em vez de uma vaga proposta. Modelo local: não cruza frentes."""

    empresa_id: Texto
    pergunta: Texto
    trecho_ambiguo: str = ""


class PropostaModelo(Contrato):
    """O que o modelo pode propor. Campo fora desta lista torna a resposta inválida."""

    titulo: str = ""
    requisitos: list[Requisito] = Field(default_factory=list)
    competencias: list[Competencia] = Field(default_factory=list)
    meta_candidatos: int | None = None
    prazo_dias: int | None = None
    duvidas: list[str] = Field(default_factory=list)


def _id_da_vaga(empresa_id: str, descricao: str) -> str:
    resumo = hashlib.sha256(f"{empresa_id}\n{descricao}".encode()).hexdigest()
    return f"vaga-{resumo[:12]}"


def _termos_no_texto(texto: str) -> list[str]:
    palavras = _palavras(texto)
    termos = TERMOS_SENSIVEIS + TERMOS_SENSIVEIS_TEXTO
    return sorted({" ".join(termo) for termo in termos if _contem(palavras, termo)})


def _restringe_quem_concorre(palavras: tuple[str, ...]) -> bool:
    if any(p in MARCADORES_DE_RESTRICAO or p.isdigit() for p in palavras):
        return True
    termos = TERMOS_SENSIVEIS + TERMOS_SENSIVEIS_TEXTO
    return any(_contem(palavras, ("para", *termo)) for termo in termos)


def _e_aviso_de_nao_discriminacao(frase: str) -> bool:
    """Reconhece o aviso frase a frase: ele não pode servir de escudo para um critério."""
    palavras = _palavras(frase)
    if _restringe_quem_concorre(palavras):
        return False
    return any(_contem(palavras, marcador) for marcador in MARCADORES_DE_AVISO)


def _pergunta_sobre_dado_sensivel(
    onde: str, termos: list[str], trecho: str, empresa_id: str
) -> PerguntaVaga:
    return PerguntaVaga(
        empresa_id=empresa_id,
        pergunta=(
            f"{onde} cita dado sensível ({', '.join(termos)}), que não pode ser critério. "
            "Reescreva o trecho sem restringir quem pode concorrer. "
            "Se for um aviso de não discriminação, deixe isso explícito na frase."
        ),
        trecho_ambiguo=trecho[:TAMANHO_MAXIMO_TRECHO],
    )


def _pergunta_sobre_texto_da_descricao(descricao: str, empresa_id: str) -> PerguntaVaga | None:
    for frase in re.split(r"[.!?;\n]+", descricao):
        termos = _termos_no_texto(frase)
        if termos and not _e_aviso_de_nao_discriminacao(frase):
            return _pergunta_sobre_dado_sensivel("A descrição", termos, frase.strip(), empresa_id)
    return None


def _pergunta_sobre_descricao(descricao: str, empresa_id: str) -> PerguntaVaga | None:
    if not descricao.strip():
        return PerguntaVaga(empresa_id=empresa_id, pergunta="Qual é a descrição da vaga?")
    if len(descricao) > TAMANHO_MAXIMO_DESCRICAO:
        return PerguntaVaga(
            empresa_id=empresa_id,
            pergunta=(
                f"A descrição passa de {TAMANHO_MAXIMO_DESCRICAO} caracteres. Pode resumi-la?"
            ),
        )
    return _pergunta_sobre_texto_da_descricao(descricao, empresa_id)


def _lacuna_da_proposta(proposta: PropostaModelo) -> str | None:
    if not proposta.titulo.strip():
        return "Qual é o título da vaga?"
    if not proposta.requisitos:
        return "Quais são os requisitos eliminatórios da vaga?"
    if not proposta.competencias:
        return "Quais competências devem pesar na análise?"
    if proposta.meta_candidatos is None:
        return "Quantos candidatos a vaga precisa receber?"
    if proposta.prazo_dias is None:
        return "Qual é o prazo da vaga, em dias?"
    return None


def _criterios_sensiveis(vaga: Vaga) -> list[str]:
    """`validar_criterios` mais a lista ampliada, sem exceção para aviso: critério é critério."""
    problemas = validar_criterios(vaga)
    for requisito in vaga.requisitos:
        texto = f"{requisito.descricao}\n{requisito.campo}\n{requisito.valor_esperado}"
        termos = _termos_no_texto(texto)
        if termos:
            problemas.append(f"requisito {requisito.id!r} usa dado sensível: {', '.join(termos)}")
    for competencia in vaga.competencias:
        termos = _termos_no_texto(competencia.nome)
        if termos:
            problemas.append(
                f"competência {competencia.nome!r} usa dado sensível: {', '.join(termos)}"
            )
    return list(dict.fromkeys(problemas))


def _vaga_ou_pergunta(
    proposta: PropostaModelo, descricao: str, empresa_id: str
) -> Vaga | PerguntaVaga:
    duvidas = [duvida.strip() for duvida in proposta.duvidas if duvida.strip()]
    if duvidas:
        return PerguntaVaga(empresa_id=empresa_id, pergunta=" ".join(duvidas))
    lacuna = _lacuna_da_proposta(proposta)
    if lacuna:
        return PerguntaVaga(empresa_id=empresa_id, pergunta=lacuna)

    vaga = Vaga(
        id=_id_da_vaga(empresa_id, descricao),
        empresa_id=empresa_id,
        titulo=proposta.titulo,
        descricao=descricao,
        requisitos=proposta.requisitos,
        competencias=proposta.competencias,
        meta_candidatos=proposta.meta_candidatos,
        prazo_dias=proposta.prazo_dias,
        max_tentativas_contato=MAX_TENTATIVAS_CONTATO,
        aprovada=False,
    )
    problemas = _criterios_sensiveis(vaga)
    if problemas:
        return PerguntaVaga(
            empresa_id=empresa_id,
            pergunta=f"A proposta foi recusada: {'; '.join(problemas)}. Como reescrever a vaga?",
        )
    termos_no_titulo = _termos_no_texto(vaga.titulo)
    if termos_no_titulo:
        return _pergunta_sobre_dado_sensivel("O título", termos_no_titulo, vaga.titulo, empresa_id)
    return vaga


def propor_configuracao(
    descricao: str, empresa_id: str, cliente_modelo: ClienteModelo
) -> Vaga | PerguntaVaga:
    """Devolve a vaga proposta, sempre com `aprovada=False`, ou uma pergunta à pessoa."""
    if not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório")

    pergunta = _pergunta_sobre_descricao(descricao, empresa_id)
    if pergunta:
        return pergunta

    proposta = cliente_modelo.completar(
        prompts.SISTEMA_CONFIGURACAO,
        prompts.USUARIO_CONFIGURACAO.format(descricao=descricao),
        PropostaModelo,
        ETAPA_CONFIGURACAO,
    )
    return _vaga_ou_pergunta(proposta, descricao, empresa_id)
