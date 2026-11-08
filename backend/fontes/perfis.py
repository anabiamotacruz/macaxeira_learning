"""Transforma `PerfilColetado` em `Candidato`, sem dar por comprovado o que não foi."""

import re
from datetime import date

from backend.agente.regras import FONTES_VERIFICAVEIS
from backend.contratos.modelos import (
    Candidato,
    ContatoColetado,
    EstadoBanco,
    PerfilColetado,
    TipoContato,
    TipoFato,
)
from backend.fontes.analisador import normalizar

ATRIBUTO_POR_TIPO = {
    TipoContato.EMAIL: "email",
    TipoContato.TELEFONE: "telefone",
    TipoContato.LINK: "links",
    TipoContato.PERFIL: "perfis",
}
_PALAVRA = re.compile(r"\w+")


def _atributos_de_contato(contatos: list[ContatoColetado]) -> dict[str, str]:
    """Só contato publicado pela própria pessoa. E-mail e telefone ficam com o primeiro."""
    atributos: dict[str, str] = {}
    for contato in contatos:
        if not contato.publicado_pela_pessoa:
            continue
        chave = ATRIBUTO_POR_TIPO[contato.tipo]
        if contato.tipo in (TipoContato.EMAIL, TipoContato.TELEFONE):
            atributos.setdefault(chave, contato.valor)
        elif chave in atributos:
            atributos[chave] += f", {contato.valor}"
        else:
            atributos[chave] = contato.valor
    return atributos


def candidato_de_perfil(
    perfil: PerfilColetado,
    *,
    origem: str,
    fonte: str | None = None,
    autorizacao_valida_ate: date | None = None,
    atributos: dict[str, str] | None = None,
) -> Candidato:
    """Fato inferido nunca entra. Sem autorização informada, a pessoa fica pendente.

    `regras.classificar_evidencia` trata como comprovado tudo o que está no texto de uma fonte
    verificável. Nela, portanto, o texto leva só o fato comprovado: bio e descrição escritas pela
    pessoa continuam em `PerfilColetado`, como declaradas, mas não viram evidência comprovada.
    """
    fonte = fonte or (perfil.fatos[0].fonte if perfil.fatos else "desconhecida")
    aceitos = {TipoFato.COMPROVADO}
    if normalizar(fonte) not in FONTES_VERIFICAVEIS:
        aceitos.add(TipoFato.DECLARADO)
    autorizado = autorizacao_valida_ate is not None
    return Candidato(
        id=perfil.candidato_id,
        empresa_id=perfil.empresa_id,
        nome=perfil.nome,
        fonte=fonte,
        simulado=perfil.simulado,
        origem=origem,
        atualizado_em=perfil.coletado_em,
        autorizacao_valida_ate=autorizacao_valida_ate,
        estado=EstadoBanco.ATIVO if autorizado else EstadoBanco.PENDENTE,
        perfil_texto="\n".join(fato.texto for fato in perfil.fatos if fato.tipo in aceitos),
        atributos={**_atributos_de_contato(perfil.contatos), **(atributos or {})},
        historico=[],
        autorizou_contato=autorizado,
    )


def combina_com_consulta(candidato: Candidato, consulta: str, *extras: str) -> bool:
    """Todas as palavras da consulta aparecem no perfil. Nome e contato ficam de fora."""
    termos = set(_PALAVRA.findall(normalizar(consulta)))
    return termos <= set(_PALAVRA.findall(normalizar(" ".join([candidato.perfil_texto, *extras]))))
