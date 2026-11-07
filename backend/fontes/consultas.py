"""Geração limitada de consultas com requisitos preservados em código (T2.7).

As consultas são texto simples, sem DSL de um provedor. Elas descobrem possíveis
perfis; a aprovação e os requisitos continuam sendo verificados pelo funil e
pelas regras determinísticas. Não fazem chamadas a fontes externas.
"""

import logging
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Vaga
from backend.fontes.prompts import SISTEMA_CONSULTAS, montar_pedido_consultas

logger = logging.getLogger(__name__)

_SENSIVEL = re.compile(
    r"\b(genero|gender|sexo|sex|idade|age|raca|race|etnia|religiao|religion|"
    r"estado civil|marital status|deficiencia|disability|orientacao sexual|"
    r"mulher|mulheres|homem|homens|masculino|feminino|casad[oa]s?|solteir[oa]s?|"
    r"jovem|jovens|idos[oa]s?|branc[oa]s?|negr[oa]s?|cristaos?|cristas?|"
    r"heterossexual|heterosexual|homossexual|homosexual|bissexual|bisexual|"
    r"gay|lesbian|lesbica|transgenero|transgender|cisgender|sexualidade|sexuality|"
    r"asian|asiatic[oa]s?|indigenas?|white|black|female|male|women|men|young|"
    r"muslim|christian|jewish|nascimento|birth|gestante|gravida|pregnant)\b"
)
_OPERADOR = re.compile(r"\b(AND|OR|NOT)\b|[\"'<>:{}()\[\]\\]|(?<!\w)-")
_INSTRUCAO = re.compile(r"\b(ignore|revele|desconsidere|instrucoes)\b")

# Apenas palavras de ligação e introduções genéricas; sem stemming ou sinônimos
# inventados. Preservamos grafia técnica (C++, C#, .NET, versões e acentos).
_PALAVRAS_DE_LIGACAO = frozenset(
    "a o as os um uma uns umas de da do das dos em na no nas nos para com e ou "
    "experiência experiencia conhecimento conhecimentos vivência vivencia "
    "experience knowledge in on of with and the required obrigatório obrigatória".split()
)


def _palavras_chave(texto: str) -> str:
    termos = re.findall(r"[\w+#]+(?:[.-][\w+#]+)*|\.NET", texto, flags=re.IGNORECASE)
    vistos = set()
    palavras = []
    for termo in termos:
        chave = termo.casefold()
        if chave not in _PALAVRAS_DE_LIGACAO and chave not in vistos:
            palavras.append(termo)
            vistos.add(chave)
    return " ".join(palavras)


class SugestoesConsultas(BaseModel):
    """Saída local do modelo; não modifica os contratos entre frentes."""

    model_config = ConfigDict(extra="forbid")
    cargos: list[StrictStr] = Field(min_length=1, max_length=6)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold().replace("_", " "))
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def _tem_sensivel(texto: str) -> bool:
    # Termos técnicos de testes não descrevem raça. O restante do texto ainda
    # passa pela checagem, inclusive se houver critério pessoal ao lado deles.
    texto = re.sub(r"\b(?:black|white)[ -]box\b", "caixa de testes", _normalizar(texto))
    return bool(_SENSIVEL.search(texto))


def _texto_seguro(texto: str, *, cargo: bool = False, proposta: bool = False) -> str:
    texto = " ".join(texto.split())
    normalizado = _normalizar(texto)
    if _tem_sensivel(texto):
        raise ValueError("critério sensível não pode ser usado em consultas")
    if (
        not texto
        or len(texto) > (120 if cargo else 500)
        or (proposta and _OPERADOR.search(texto))
        or _INSTRUCAO.search(normalizado)
        or (cargo and re.search(r"\b\d+\s*(anos?|years?)\b", normalizado))
    ):
        raise ValueError("texto inválido para consulta profissional simples")
    return texto


def _dados_vaga(vaga: Vaga) -> tuple[str, list[str]]:
    titulo = _texto_seguro(vaga.titulo, cargo=True)
    requisitos = []
    for requisito in vaga.requisitos:
        # Campo e valor também são checados para não esconder critérios proibidos
        # atrás de uma descrição aparentemente neutra.
        if _tem_sensivel(f"{requisito.campo} {requisito.valor_esperado}"):
            raise ValueError("critério sensível não pode ser usado em consultas")
        descricao = _texto_seguro(requisito.descricao)
        valor = requisito.valor_esperado.strip()
        if valor and _normalizar(valor) not in {"sim", "true", "yes"}:
            descricao = f"{descricao} {_texto_seguro(valor)}"
        requisitos.append(descricao)
    for competencia in vaga.competencias:
        _texto_seguro(competencia.nome)
    return titulo, list(dict.fromkeys(requisitos))


def _registrar(vaga: Vaga, etapa: str, regra: str, quantidade: int) -> None:
    logger.info(
        "Geração de consultas registrada",
        extra={"empresa_id": vaga.empresa_id, "vaga_id": vaga.id, "etapa": etapa,
               "regra": regra, "quantidade": quantidade},
    )


def _gerar(vaga: Vaga, cliente: ClienteModelo, *, ampliar: bool) -> list[str]:
    titulo, _ = _dados_vaga(vaga)
    etapa = "ampliar_consultas" if ampliar else "gerar_consultas"
    _registrar(vaga, etapa, "solicitar_sinonimos", 0)
    try:
        resposta = cliente.completar(
            sistema=SISTEMA_CONSULTAS,
            usuario=montar_pedido_consultas(titulo, ampliar),
            esquema=SugestoesConsultas,
            etapa=etapa,
        )
        sugestoes = SugestoesConsultas.model_validate(resposta.model_dump())
        cargos = [
            titulo,
            *[_texto_seguro(cargo, cargo=True, proposta=True) for cargo in sugestoes.cargos],
        ]
        regra = "sinonimos_validados"
    except (RespostaInvalida, ModeloIndisponivel, ValidationError, ValueError):
        cargos, regra = [titulo], "consulta_basica"

    termos_requisitos = [
        requisito.valor_esperado
        if requisito.valor_esperado.strip()
        and _normalizar(requisito.valor_esperado) not in {"sim", "true", "yes"}
        else requisito.descricao
        for requisito in vaga.requisitos
    ]
    palavras = _palavras_chave(" ".join(termos_requisitos))
    # Cada termo é uma alternativa de descoberta. Requisitos conjuntos são
    # verificados depois em código, nunca pela coocorrência literal no currículo.
    alternativas = palavras.split()
    if regra == "sinonimos_validados" or not alternativas:
        alternativas.extend(cargos)
    consultas = []
    vistos = set()
    for consulta in alternativas:
        chave = _normalizar(consulta)
        if chave not in vistos:
            consultas.append(consulta)
            vistos.add(chave)
    _registrar(vaga, etapa, regra, len(consultas))
    return consultas


def gerar_consultas(vaga: Vaga, cliente_modelo: ClienteModelo) -> list[str]:
    """Gera palavras-chave dos requisitos e variações adicionais de cargo."""
    return _gerar(vaga, cliente_modelo, ampliar=False)


def ampliar_consultas(
    vaga: Vaga, anteriores: list[str], cliente_modelo: ClienteModelo
) -> list[str]:
    """Retorna somente consultas novas; lista vazia significa expansão esgotada.

    Consultas anteriores nunca são reenviadas ao modelo nem executadas aqui.
    A expansão muda os cargos sugeridos, sem retirar os requisitos da vaga.
    """
    anteriores_normalizadas = {_normalizar(consulta) for consulta in anteriores}
    novas = _gerar(vaga, cliente_modelo, ampliar=True)
    return [consulta for consulta in novas if _normalizar(consulta) not in anteriores_normalizadas]
