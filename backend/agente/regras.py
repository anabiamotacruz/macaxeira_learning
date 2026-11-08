"""Regras determinísticas de critérios, requisitos, contato e decisão. Nenhuma usa modelo de IA."""

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from backend.agente.auditoria import responsavel_do_mandato
from backend.agente.mandato import Mandato, MandatoInvalido, mandato_valido
from backend.agente.neutralizacao import corresponde_ao_original
from backend.contratos.criterios import TERMOS_SENSIVEIS as TERMOS_SENSIVEIS
from backend.contratos.criterios import (
    campo_sensivel,
    frases_restritivas,
    sem_acento,
    termos_sensiveis,
)
from backend.contratos.criterios import contem_termo as contem_termo
from backend.contratos.criterios import separar_palavras as separar_palavras
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Decisao,
    EstadoBanco,
    Evidencia,
    Requisito,
    TipoDecisao,
    Vaga,
)

FONTES_VERIFICAVEIS = frozenset({"github", "rede_simulada"})
"""Fontes externas à autodeclaração. Currículo e perfil enviado pela pessoa ficam de fora."""

FONTE_REGRA = "regra_deterministica"
"""Fonte da evidência criada por código, quando a decisão não tem trecho do perfil para citar."""


PREFIXO_REGRA_FUNIL = "funil:"
PREFIXO_RESPONSAVEL_AGENTE = "agente:"
CORTES_POR_AUTORIZACAO = frozenset(
    {"autorizacao_vencida", "estado_bloqueado", "opt_out", "sem_autorizacao"}
)
"""Quem sai por estes cortes não autorizou o uso do perfil nesta vaga."""

CORTES_QUE_DESCARTAM = CORTES_POR_AUTORIZACAO | {"duplicata", "requisito_nao_atendido"}
"""Fora do limite não descarta: a pessoa é elegível e só não coube nas análises da rodada."""

CORTES_SEM_DECISAO = frozenset({"reserva"})
"""Ninguém decidiu sobre a pessoa: ela segue no banco, sem análise, e pode voltar em outra rodada.
Fica só o evento, para não encher a fila humana com quem não mostrou ligação com a vaga."""

REGRA_PERFIL_DESATUALIZADO = "perfil_desatualizado"
"""Não é mais corte: com autorização válida, o perfil desatualizado é analisado e decidido, e o
pacote pede para confirmar o perfil com a pessoa."""

ESTADOS_COM_AUTORIZACAO = frozenset({EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO})
"""Perfil desatualizado continua autorizado: o que envelheceu é o texto, não o consentimento."""

LIMIAR_PADRAO = 0.7
"""Limiar usado quando o mandato não define `limiar_verde`: o agente decide sempre."""

NOTA_SEM_RESPOSTA = 0.15
"""Nota de quem segue sem nota válida depois do novo pedido: a de nada no perfil se relaciona."""

TETO_SEM_TRECHO = 0.5
"""Sem trecho do perfil, a nota não passa da de competência inferida: nada sem evidência indica."""

TETO_COM_RESSALVA = 0.5
"""A ressalva do revisor sobre uma competência limita a nota dela antes da média."""

TETO_COM_ALERTA = 0.8
"""Com texto dirigido ao avaliador, nenhuma nota chega ao topo da escala."""

RESSALVA_NOTA_SEM_EVIDENCIA = "nota_sem_evidencia"
RESSALVA_REVISOR_INVALIDO = "revisor_resposta_invalida"


class CorteFunil(Protocol):
    """Saída do funil, sem dados do perfil. A frente de fontes define os valores de `regra`."""

    candidato_id: str
    fonte: str
    origem: str
    regra: str
    motivo: str


class StatusRequisito(StrEnum):
    ATENDE = "atende"
    NAO_ATENDE = "nao_atende"
    SEM_DADO = "sem_dado"


SEM_DADO = StatusRequisito.SEM_DADO


class TipoEvidencia(StrEnum):
    INFERIDA = "inferida"
    DECLARADA = "declarada"
    COMPROVADA = "comprovada"


def _problemas_do_requisito(requisito: Requisito) -> list[str]:
    termos = termos_sensiveis(requisito.descricao, requisito.campo, requisito.valor_esperado)
    if campo_sensivel(requisito.campo) and requisito.campo.strip():
        termos = sorted({*termos, *separar_palavras(requisito.campo)})
    if termos:
        return [f"requisito {requisito.id!r} usa dado sensível: {', '.join(termos)}"]
    if not requisito.valor_esperado.strip() or not requisito.campo.strip():
        return [f"requisito {requisito.id!r} sem atributo ou valor esperado: nunca eliminaria"]
    return []


def validar_requisitos_e_competencias(vaga: Vaga) -> list[str]:
    """Um problema por critério, em ordem estável. Critério não tem exceção para aviso."""
    problemas = [p for requisito in vaga.requisitos for p in _problemas_do_requisito(requisito)]
    for competencia in vaga.competencias:
        termos = termos_sensiveis(competencia.nome)
        if termos:
            problemas.append(
                f"competência {competencia.nome!r} usa dado sensível: {', '.join(termos)}"
            )
    return problemas


def requisitos_sem_valor(vaga: Vaga) -> list[str]:
    """Requisitos que nunca eliminariam ninguém, por não dizerem o atributo ou o valor."""
    return [
        requisito.id
        for requisito in vaga.requisitos
        if not requisito.valor_esperado.strip() or not requisito.campo.strip()
    ]


def validar_criterios(vaga: Vaga) -> list[str]:
    """Lista os problemas da vaga: critérios, título e descrição com dado sensível.

    Título e descrição são texto livre e costumam trazer aviso de não discriminação, que cita
    esses mesmos termos: só a frase que restringe quem concorre, como `apenas homens`, é problema.
    """
    problemas = validar_requisitos_e_competencias(vaga)
    if termos_sensiveis(vaga.titulo):
        problemas.append(f"título usa dado sensível: {', '.join(termos_sensiveis(vaga.titulo))}")
    for _, termos in frases_restritivas(vaga.descricao):
        problemas.append(f"descrição restringe por dado sensível: {', '.join(termos)}")
    return problemas


def _exigir_mesma_empresa(vaga: Vaga, candidato: Candidato) -> None:
    if vaga.empresa_id != candidato.empresa_id:
        raise ValueError("vaga e candidato pertencem a empresas diferentes")


def _normalizar_valor(texto: str) -> str:
    """Tira acento, caixa e espaços repetidos, mantendo símbolos: `C++` não é `C#`."""
    return " ".join(sem_acento(texto).casefold().split())


def _status_requisito(requisito: Requisito, candidato: Candidato) -> StatusRequisito:
    esperado = _normalizar_valor(requisito.valor_esperado)
    atual = _normalizar_valor(candidato.atributos.get(requisito.campo, ""))
    if not esperado or not atual:
        return StatusRequisito.SEM_DADO
    return StatusRequisito.ATENDE if atual == esperado else StatusRequisito.NAO_ATENDE


def avaliar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, StatusRequisito]:
    """Compara cada requisito com o atributo do candidato. Dado ausente é SEM_DADO."""
    _exigir_mesma_empresa(vaga, candidato)
    return {r.id: _status_requisito(r, candidato) for r in vaga.requisitos}


def verificar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, bool]:
    """Diz quais requisitos estão atendidos.

    False junta NAO_ATENDE e SEM_DADO. Para reprovar alguém, use `avaliar_requisitos`.
    """
    return {
        id_requisito: status == StatusRequisito.ATENDE
        for id_requisito, status in avaliar_requisitos(vaga, candidato).items()
    }


def autorizacao_ativa(candidato: Candidato, hoje: date) -> bool:
    """Diz se a pessoa está ativa e autorizou. A autorização vale até o dia de `valida_ate`."""
    validade = candidato.autorizacao_valida_ate
    return (
        candidato.estado in ESTADOS_COM_AUTORIZACAO
        and candidato.autorizou_contato
        and not candidato.opt_out
        and validade is not None
        and validade >= hoje
    )


MAX_CONTATOS_PELO_PUBLICADO = 2
"""E-mail inicial e um único lembrete, como em `backend/contato/email_inicial.py`."""


def externo_sem_autorizacao(candidato: Candidato) -> bool:
    """Veio de fonte externa e nunca registrou autorização: pode ser analisada (decisão de 8/11).

    É como `candidato_de_item` entrega quem vem da busca real: dado real, pendente, sem
    autorização e sem validade. Opt-out, remoção e autorização que existiu e venceu ficam de fora
    e continuam cortando. O contato dessa pessoa só sai pelo e-mail que ela mesma publicou
    (`pode_contatar_pelo_publicado`), e o aceite do convite registra a autorização.

    Limites conhecidos:
    - A autorização vencida só corta quando o registro do banco tem o mesmo `id` do registro
      externo. Casar a mesma pessoa entre fontes com ids diferentes depende da resolução de
      identidade (spec 004, T044); até lá, um registro externo de id novo segue para a análise.
    - A busca real só gera convite quando a fonte traz um e-mail publicado pela própria pessoa.
      Hoje nenhuma fonte ligada à busca real extrai isso: o e-mail de provedor vem marcado como
      não publicado. Sem ele, a pessoa fica indicada e o motivo `contato_nao_publicado` vai para
      os eventos.
    """
    return (
        not candidato.simulado
        and not candidato.opt_out
        and not candidato.autorizou_contato
        and candidato.autorizacao_valida_ate is None
        and candidato.estado == EstadoBanco.PENDENTE
    )


def pode_ir_ao_modelo(candidato: Candidato, hoje: date) -> bool:
    """Autorização ativa ou pessoa externa que nunca teve autorização registrada."""
    return autorizacao_ativa(candidato, hoje) or externo_sem_autorizacao(candidato)


@dataclass(frozen=True)
class CorteDeAutorizacao:
    """Saída de quem não pode ir ao modelo, para o fluxo sem funil. Sem dados do perfil."""

    candidato_id: str
    fonte: str
    origem: str
    regra: str
    motivo: str


def corte_de_autorizacao(candidato: Candidato, hoje: date) -> CorteDeAutorizacao | None:
    """Diz por que a pessoa não pode ir ao modelo. Mesmas regras do funil, para um só registro."""
    validade = candidato.autorizacao_valida_ate

    def corte(regra: str, motivo: str) -> CorteDeAutorizacao:
        return CorteDeAutorizacao(candidato.id, candidato.fonte, candidato.origem, regra, motivo)

    if candidato.opt_out:
        return corte("opt_out", "a pessoa pediu para não ser contatada")
    if candidato.estado == EstadoBanco.REMOVIDO:
        return corte("estado_bloqueado", "perfil removido")
    if externo_sem_autorizacao(candidato):
        return None
    if not candidato.autorizou_contato or validade is None:
        return corte("sem_autorizacao", "sem autorização registrada")
    if validade < hoje:
        return corte("autorizacao_vencida", f"autorização vencida em {validade.isoformat()}")
    if candidato.estado in (EstadoBanco.PENDENTE, EstadoBanco.EXPIRADO):
        return corte("estado_bloqueado", f"perfil com estado {candidato.estado}")
    return None


def pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga, hoje: date) -> bool:
    """Diz se o candidato pode receber contato sobre a vaga.

    `tentativas` conta os contatos já feitos.
    """
    _exigir_mesma_empresa(vaga, candidato)
    return autorizacao_ativa(candidato, hoje) and 0 <= tentativas < vaga.max_tentativas_contato


def pode_contatar_pelo_publicado(
    candidato: Candidato, tentativas: int, vaga: Vaga, *, tem_contato_publicado: bool
) -> bool:
    """Contato de quem nunca autorizou: só pelo e-mail que a pessoa publicou, no máximo duas vezes.

    `tem_contato_publicado` vem de `contato_publicado`: contato inferido ou de provedor não vale.
    """
    _exigir_mesma_empresa(vaga, candidato)
    limite = min(vaga.max_tentativas_contato, MAX_CONTATOS_PELO_PUBLICADO)
    return tem_contato_publicado and externo_sem_autorizacao(candidato) and 0 <= tentativas < limite


def _trecho_no_perfil(trecho: str, perfil: str) -> bool:
    """Confere o trecho inteiro, palavra a palavra: `Java` não confere com `JavaScript`.

    Evidência pseudonimizada traz marcadores, e o gênero não conta: o perfil guardado é o original.
    """
    return corresponde_ao_original(trecho, perfil)


def classificar_evidencia(evidencia: Evidencia, candidato: Candidato) -> TipoEvidencia:
    """Dá o tipo da evidência por código, sem confiar no que o modelo afirma.

    Sem o trecho literal no perfil, é INFERIDA. COMPROVADA exige que a fonte citada seja
    verificável e igual à fonte do perfil conferido: citar `github` num currículo não promove.
    """
    if not _trecho_no_perfil(evidencia.trecho, candidato.perfil_texto):
        return TipoEvidencia.INFERIDA
    fonte = _normalizar_valor(evidencia.fonte)
    if fonte in FONTES_VERIFICAVEIS and fonte == _normalizar_valor(candidato.fonte):
        return TipoEvidencia.COMPROVADA
    return TipoEvidencia.DECLARADA


@dataclass(frozen=True)
class Faixa:
    """Resultado da regra da faixa verde, antes de virar `Decisao`.

    `faltas` diz o que levou à decisão; `sinais` registra o que foi visto e não a mudou;
    `ajustes` explica cada nota que a regra limitou ou completou antes da média.
    """

    tipo: TipoDecisao
    regra: str
    faltas: tuple[str, ...]
    nota: float | None
    requisitos: dict[str, StatusRequisito]
    evidencias: tuple[tuple[str, TipoEvidencia], ...]
    limiar: float = LIMIAR_PADRAO
    piso: float = 0.0
    limiar_do_mandato: bool = True
    notas_modelo: tuple[tuple[str, float | None], ...] = ()
    notas_usadas: tuple[tuple[str, float], ...] = ()
    ajustes: tuple[str, ...] = ()
    sinais: tuple[str, ...] = ()


def _pesos_validos(vaga: Vaga) -> bool:
    pesos = [c.peso for c in vaga.competencias]
    return all(math.isfinite(peso) and peso >= 0 for peso in pesos) and sum(pesos) > 0


def _nota_ponderada(vaga: Vaga, notas: dict[str, float]) -> float | None:
    """Média das notas pelos pesos. Devolve None se a vaga não tem peso válido."""
    if not _pesos_validos(vaga):
        return None
    pesos = [c.peso for c in vaga.competencias]
    valores = [notas[c.nome] for c in vaga.competencias]
    return round(sum(p * n for p, n in zip(pesos, valores, strict=True)) / sum(pesos), 6)


def _criterio_da_ressalva(ressalva: str) -> str | None:
    """`criterio: problema Trecho: ...` do revisor, ou `nota_sem_evidencia: criterio`."""
    prefixo, separador, resto = ressalva.partition(":")
    if not separador:
        return None
    return resto.strip() if prefixo.strip() == RESSALVA_NOTA_SEM_EVIDENCIA else prefixo.strip()


def _nota_valida(nota: float | None) -> bool:
    return nota is not None and math.isfinite(nota) and 0 <= nota <= 1


def _formatar(nota: float) -> str:
    return f"{round(nota, 6):g}"


def _notas_da_decisao(
    vaga: Vaga, analise: Analise, evidencias: tuple[tuple[str, TipoEvidencia], ...]
) -> tuple[dict[str, float], list[str], list[str]]:
    """A nota de cada competência que entra na média, com os ajustes e os sinais que a explicam.

    Sem nota válida, entra `NOTA_SEM_RESPOSTA`. Depois, cada teto que vale para a competência:
    sem trecho do perfil, com ressalva do revisor e com alerta. O teto só reduz, nunca sobe.
    """
    com_trecho = {c for c, tipo in evidencias if tipo != TipoEvidencia.INFERIDA}
    ressalvadas = {_criterio_da_ressalva(r) for r in analise.ressalvas_revisor}
    usadas: dict[str, float] = {}
    ajustes: list[str] = []
    sinais: list[str] = []
    for competencia in vaga.competencias:
        nome = competencia.nome
        original = analise.notas.get(nome)
        if _nota_valida(original):
            nota = float(original)
        else:
            nota = NOTA_SEM_RESPOSTA
            ajustes.append(f"{nome} sem nota válida do modelo: entrou com {NOTA_SEM_RESPOSTA}")
            sinais.append(f"nota_padrao:{nome}")
        tetos = []
        if nome not in com_trecho:
            tetos.append((TETO_SEM_TRECHO, "sem trecho do perfil"))
            sinais.append(f"sem_trecho:{nome}")
        if nome in ressalvadas:
            tetos.append((TETO_COM_RESSALVA, "por ressalva do revisor"))
            sinais.append(f"ressalva_do_revisor:{nome}")
        if analise.alertas:
            tetos.append((TETO_COM_ALERTA, "por alerta"))
        for teto, porque in sorted(tetos):
            if nota > teto:
                ajustes.append(
                    f"{nome} limitada a {_formatar(teto)} {porque} (modelo deu {_formatar(nota)})"
                )
                nota = teto
        usadas[nome] = nota
    return usadas, ajustes, sinais


def _sinais_da_analise(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    requisitos: dict[str, StatusRequisito],
    evidencias: tuple[tuple[str, TipoEvidencia], ...],
) -> list[str]:
    """O que não muda a decisão, mas precisa ficar registrado e chegar ao pacote."""
    competencias = {c.nome for c in vaga.competencias}
    sinais = [f"requisito_sem_dado:{i}" for i, s in sorted(requisitos.items()) if s == SEM_DADO]
    if candidato.estado == EstadoBanco.DESATUALIZADO:
        sinais.append(REGRA_PERFIL_DESATUALIZADO)
    if analise.alertas:
        sinais.append("alerta")
    for ressalva in analise.ressalvas_revisor:
        if ressalva.strip() == RESSALVA_REVISOR_INVALIDO:
            continue
        if _criterio_da_ressalva(ressalva) not in competencias:
            sinais.append("ressalva_do_revisor")
    inexistentes = sorted({c for c, tipo in evidencias if tipo == TipoEvidencia.INFERIDA})
    sinais += [f"trecho_inexistente:{c}" for c in inexistentes]
    return list(dict.fromkeys(sinais))


def _exigir_mesma_execucao(
    vaga: Vaga, candidato: Candidato, analise: Analise, mandato: Mandato
) -> None:
    _exigir_mesma_empresa(vaga, candidato)
    if analise.empresa_id != vaga.empresa_id or mandato.empresa_id != vaga.empresa_id:
        raise ValueError("análise e mandato precisam ser da empresa da vaga")
    if analise.vaga_id != vaga.id or mandato.vaga_id != vaga.id:
        raise ValueError("análise e mandato precisam ser da mesma vaga")
    if analise.candidato_id != candidato.id:
        raise ValueError("análise precisa ser do mesmo candidato")


def classificar_faixa(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
) -> Faixa:
    """Aplica a regra da faixa verde: o agente indica ou descarta pela nota, como recrutador.

    Autorização e requisito eliminatório não atendido descartam só por código. Fora isso, a nota
    ponderada decide: a partir do limiar indica, abaixo dele descarta, e o RH pode reverter.
    Requisito sem dado, perfil desatualizado, alerta e ressalva não levam a uma pessoa: ficam em
    `sinais`, e alerta e ressalva limitam notas antes da média. Só vão a uma pessoa a vaga sem peso
    válido e a revisão que falhou, como a análise inválida. Não usa nome, atributo sensível nem
    confiança declarada pelo modelo. Levanta `ValueError` se as peças são de empresas, vagas ou
    candidatos diferentes, e `MandatoInvalido` se o mandato não vale para a vaga ou se ela usa
    critério sensível, para o fluxo pausar.
    """
    _exigir_mesma_execucao(vaga, candidato, analise, mandato)
    if not mandato_valido(mandato, vaga, agora):
        raise MandatoInvalido("mandato não vale para esta vaga neste momento")
    problemas = validar_criterios(vaga)
    if problemas:
        raise MandatoInvalido(f"vaga com problemas nos critérios: {'; '.join(problemas)}")

    politica = mandato.politica
    requisitos = avaliar_requisitos(vaga, candidato)
    evidencias = tuple(
        (e.criterio, classificar_evidencia(e, candidato)) for e in analise.evidencias
    )
    limiar = LIMIAR_PADRAO if politica.limiar_verde is None else politica.limiar_verde
    usadas, ajustes, sinais_notas = _notas_da_decisao(vaga, analise, evidencias)
    nota = _nota_ponderada(vaga, usadas)
    sinais = (*_sinais_da_analise(vaga, candidato, analise, requisitos, evidencias), *sinais_notas)

    def faixa(tipo: TipoDecisao, regra: str, faltas: tuple[str, ...] = ()) -> Faixa:
        return Faixa(
            tipo,
            regra,
            faltas,
            nota,
            requisitos,
            evidencias,
            limiar=limiar,
            piso=politica.piso_nota,
            limiar_do_mandato=politica.limiar_verde is not None,
            notas_modelo=tuple((c.nome, analise.notas.get(c.nome)) for c in vaga.competencias),
            notas_usadas=tuple(sorted(usadas.items())),
            ajustes=tuple(ajustes),
            sinais=sinais,
        )

    if not pode_ir_ao_modelo(candidato, hoje):
        return faixa(TipoDecisao.DESCARTAR, "sem_autorizacao")
    reprovados = sorted(i for i, s in requisitos.items() if s == StatusRequisito.NAO_ATENDE)
    if reprovados:
        faltas = tuple(f"requisito_eliminatorio:{i}" for i in reprovados)
        return faixa(TipoDecisao.DESCARTAR, faltas[0], faltas)
    if nota is None:
        # A vaga não tem peso válido: é configuração, não algo que a nota da pessoa resolva.
        return faixa(TipoDecisao.PEDIR_HUMANO, "fora_da_faixa_verde", ("pesos_invalidos",))
    if RESSALVA_REVISOR_INVALIDO in (r.strip() for r in analise.ressalvas_revisor):
        # Falha do modelo, como a análise inválida: sem a revisão independente, decide uma pessoa.
        return faixa(TipoDecisao.PEDIR_HUMANO, "fora_da_faixa_verde", ("revisao_invalida",))
    if nota >= limiar:
        return faixa(TipoDecisao.INDICAR, "faixa_verde_v1")
    if nota < politica.piso_nota:
        return faixa(TipoDecisao.DESCARTAR, "abaixo_do_piso", ("nota_abaixo_do_piso",))
    return faixa(TipoDecisao.DESCARTAR, "abaixo_do_limiar", ("nota_abaixo_do_limiar",))


_PARECE_INSTRUCAO = re.compile(
    r"\b(aprov(e|ar|ado|ada)|contrat(e|ar)|desconsider(e|ar)|ignor(e|ar)|indiqu(e|em)|indicar|"
    r"reprov(e|ar))\b"
)


def parece_instrucao(texto: str) -> bool:
    """Texto livre do modelo pode repetir uma instrução do perfil: ela não segue adiante."""
    return _PARECE_INSTRUCAO.search(" ".join(separar_palavras(texto))) is not None


def evidencia_da_regra(regra: str, motivo: str) -> Evidencia:
    """Registra o fato que a regra usou. Não vem do modelo nem é trecho do perfil."""
    return Evidencia(criterio=regra, trecho=motivo, fonte=FONTE_REGRA)


def _evidencia_completa(evidencia: Evidencia) -> bool:
    return all(texto.strip() for texto in (evidencia.criterio, evidencia.trecho, evidencia.fonte))


def _entrada(
    vaga: Vaga, candidato: Candidato, mandato: Mandato, faixa: Faixa, hoje: date
) -> dict[str, str]:
    """O que sustentou a decisão, sem nome, atributos nem texto do candidato."""
    return {
        "vaga_id": vaga.id,
        "candidato_id": candidato.id,
        "hoje": hoje.isoformat(),
        "mandato_id": mandato.id,
        "mandato_versao": str(mandato.versao),
        "hash_vaga": mandato.hash_vaga,
        "limiar_verde": str(faixa.limiar),
        "limiar_origem": "mandato" if faixa.limiar_do_mandato else "padrao",
        "piso_nota": str(mandato.politica.piso_nota),
        "aceitar_declarada": str(mandato.politica.aceitar_declarada).lower(),
        "nota": "indefinida" if faixa.nota is None else str(faixa.nota),
        "notas_modelo": json.dumps(dict(faixa.notas_modelo), sort_keys=True),
        "notas_usadas": json.dumps(dict(faixa.notas_usadas), sort_keys=True),
        "ajustes": json.dumps(faixa.ajustes, ensure_ascii=False),
        "sinais": json.dumps(faixa.sinais, ensure_ascii=False),
        "requisitos": json.dumps(faixa.requisitos, sort_keys=True),
        "tipos_evidencia": json.dumps(sorted(faixa.evidencias)),
        "faltas": json.dumps(faixa.faltas),
    }


_TEXTO_DO_SINAL = {
    REGRA_PERFIL_DESATUALIZADO: "perfil desatualizado: confirmar com a pessoa",
    "alerta": "alerta: texto dirigido ao avaliador retirado da análise",
    "ressalva_do_revisor": "ressalva do revisor sem competência da vaga",
}


def _motivo(faixa: Faixa) -> str:
    """Nota e limiar, depois cada ajuste e cada sinal: dá para refazer a conta a partir dele."""
    if faixa.nota is None:
        partes = [", ".join(faixa.faltas)]
    elif faixa.tipo == TipoDecisao.PEDIR_HUMANO:
        partes = [
            f"{', '.join(faixa.faltas)}: a revisão independente voltou inválida, "
            f"nota {_formatar(faixa.nota)} e limiar {_formatar(faixa.limiar)}"
        ]
    else:
        nota, limiar = _formatar(faixa.nota), _formatar(faixa.limiar)
        if faixa.tipo == TipoDecisao.INDICAR:
            partes = [f"nota {nota} atinge o limiar {limiar}"]
        elif faixa.regra == "abaixo_do_piso":
            partes = [f"nota {nota} abaixo do piso {_formatar(faixa.piso)} (limiar {limiar})"]
        else:
            partes = [f"nota {nota} abaixo do limiar {limiar}"]
    if not faixa.limiar_do_mandato:
        partes.append(f"limiar padrão {_formatar(LIMIAR_PADRAO)}: o mandato não define limiar")
    partes += faixa.ajustes
    for sinal in faixa.sinais:
        if sinal in _TEXTO_DO_SINAL:
            partes.append(_TEXTO_DO_SINAL[sinal])
        elif sinal.startswith("requisito_sem_dado:"):
            partes.append(f"confirmar com a pessoa o requisito {sinal.partition(':')[2]}")
    return "; ".join(partes)


def decidir(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
    rastro_id: str,
) -> Decisao:
    """Transforma a faixa em `Decisao`, com regra, entrada, evidências e responsável."""
    faixa = classificar_faixa(vaga, candidato, analise, mandato, hoje, agora)
    if faixa.regra == "sem_autorizacao":
        corte = corte_de_autorizacao(candidato, hoje)
        motivo = "sem autorização válida" if corte is None else corte.motivo
    elif faixa.regra.startswith("requisito_eliminatorio:"):
        motivo = ", ".join(faixa.faltas)
    else:
        motivo = _motivo(faixa)
    evidencias = [e for e in analise.evidencias if _evidencia_completa(e)]
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=faixa.tipo,
        regra=faixa.regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada=_entrada(vaga, candidato, mandato, faixa, hoje),
        evidencias=evidencias or [evidencia_da_regra(faixa.regra, motivo)],
        momento=agora,
    )


def alem_do_teto(decisao: Decisao, limite: int) -> Decisao:
    """Segura quem estava na faixa verde além do teto de segurança do mandato.

    Não vai a uma pessoa: fica registrada como descarte com a nota e o teto, para o RH reverter.
    """
    nota = decisao.entrada.get("nota")
    nota_texto = f"nota {float(nota):.2f}" if nota is not None else "nota não informada"
    return decisao.model_copy(
        update={
            "tipo": TipoDecisao.DESCARTAR,
            "regra": "alem_do_teto_do_mandato",
            "motivo": (
                f"estava na faixa verde ({nota_texto}), mas o teto de segurança do mandato "
                f"é de {limite} indicações; o RH pode reverter"
            ),
        }
    )


def decisao_sem_analise(
    vaga: Vaga, candidato: Candidato, mandato: Mandato, agora: datetime, rastro_id: str
) -> Decisao:
    """Falha individual: sem análise válida, a decisão fica com uma pessoa."""
    regra, motivo = "analise_invalida", "a análise voltou inválida"
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=TipoDecisao.PEDIR_HUMANO,
        regra=regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada={
            "vaga_id": vaga.id,
            "candidato_id": candidato.id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
        },
        evidencias=[evidencia_da_regra(regra, motivo)],
        momento=agora,
    )


def decisao_de_corte(
    corte: CorteFunil, mandato: Mandato, agora: datetime, rastro_id: str
) -> Decisao:
    """Transforma a saída do funil em decisão. Regra desconhecida fica com uma pessoa."""
    regra = f"{PREFIXO_REGRA_FUNIL}{corte.regra}"
    descarta = str(corte.regra) in CORTES_QUE_DESCARTAM
    return Decisao(
        empresa_id=mandato.empresa_id,
        vaga_id=mandato.vaga_id,
        candidato_id=corte.candidato_id,
        tipo=TipoDecisao.DESCARTAR if descarta else TipoDecisao.PEDIR_HUMANO,
        regra=regra,
        motivo=corte.motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada={
            "vaga_id": mandato.vaga_id,
            "candidato_id": corte.candidato_id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
            "hoje": agora.date().isoformat(),
            "fonte": corte.fonte or "nao_informada",
            "origem": corte.origem or "nao_informada",
        },
        evidencias=[evidencia_da_regra(regra, corte.motivo)],
        momento=agora,
    )


def decisao_por_novos_requisitos(
    vaga: Vaga,
    candidato: Candidato,
    anterior: Decisao,
    mandato: Mandato,
    agora: datetime,
) -> Decisao | None:
    """Reavalia quem estava indicado contra a vaga do aditivo. `None` se a indicação continua.

    Falta comprovada descarta. Dado ausente tira da faixa verde só a decisão automática: a
    pessoa que indicou alguém sem o dado já tomou essa decisão.
    """
    status = avaliar_requisitos(vaga, candidato)
    reprovados = sorted(i for i, s in status.items() if s == StatusRequisito.NAO_ATENDE)
    sem_dado = sorted(i for i, s in status.items() if s == SEM_DADO)
    if reprovados:
        tipo, regra = TipoDecisao.DESCARTAR, f"requisito_eliminatorio:{reprovados[0]}"
        motivo = f"requisito do aditivo não atendido: {', '.join(reprovados)}"
    elif sem_dado and anterior.responsavel.startswith(PREFIXO_RESPONSAVEL_AGENTE):
        tipo, regra = TipoDecisao.PEDIR_HUMANO, "requisito_sem_dado_no_aditivo"
        motivo = f"requisito do aditivo sem dado: {', '.join(sem_dado)}"
    else:
        return None
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=tipo,
        regra=regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=anterior.rastro_id,
        entrada={
            "vaga_id": vaga.id,
            "candidato_id": candidato.id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
            "regra_anterior": anterior.regra,
            "requisitos": json.dumps(status, sort_keys=True),
        },
        evidencias=[evidencia_da_regra(regra, motivo)],
        momento=agora,
    )


def criterios_sem_evidencia(vaga: Vaga, candidato: Candidato, analise: Analise) -> list[str]:
    """Critérios relevantes sem nenhuma evidência conferida, comprovada ou declarada."""
    conferidos = {
        e.criterio
        for e in analise.evidencias
        if classificar_evidencia(e, candidato) != TipoEvidencia.INFERIDA
    }
    criterios = [r.id for r in vaga.requisitos]
    criterios += [c.nome for c in vaga.competencias if c.peso > 0]
    return [criterio for criterio in criterios if criterio not in conferidos]
