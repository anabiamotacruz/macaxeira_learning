"""Aprendizado pelo resultado da entrevista (T1.5). Sugere; quem decide é uma pessoa.

Quando os indicados de uma vaga reprovam repetidamente na entrevista no mesmo critério, o agente
está aceitando evidência fraca demais nele. A proposta dá mais peso a esse critério, para a nota
ponderada exigir mais dele. Ela nunca entra sozinha: `aplicar` recusa proposta sem aprovação de
uma pessoa nomeada, e `reverter` devolve a vaga de antes.

Pelo plano da spec 005 (R7), este caminho é alerta, nunca portão: não mexe em limiar nem em prompt.
Só critérios que já estão na vaga entram, e a vaga proposta passa de novo por `validar_criterios`,
então atributo sensível nunca vira critério. A vaga proposta volta sem aprovação: assinar o
mandato de novo é decisão do RH.
"""

from collections.abc import Sequence

from backend.agente.fluxo import exigir_humano
from backend.agente.regras import validar_criterios
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import PropostaAjuste, ResultadoEntrevista, Vaga

NOTA_DE_REPROVACAO = 0.5
"""Nota do critério abaixo da qual a entrevista conta como reprovação nele."""
MIN_ENTREVISTAS = 3
TAXA_MINIMA = 0.6
"""Fração das entrevistas com reprovação no mesmo critério para sugerir o ajuste."""
FATOR_DE_PESO = 1.5


class AjusteNaoAprovado(ErroContrato, ValueError):
    """A proposta ainda não foi aprovada por uma pessoa."""


def propor_ajuste(vaga: Vaga, resultados: Sequence[ResultadoEntrevista]) -> PropostaAjuste | None:
    """Sugere mais peso ao critério com reprovação repetida, ou `None` se não houver padrão."""
    da_vaga = [r for r in resultados if (r.empresa_id, r.vaga_id) == (vaga.empresa_id, vaga.id)]
    if len(da_vaga) < MIN_ENTREVISTAS:
        return None
    criterios = {c.nome for c in vaga.competencias}
    reprovacoes = {
        nome: sum(1 for r in da_vaga if r.notas.get(nome, 1.0) < NOTA_DE_REPROVACAO)
        for nome in sorted(criterios)
    }
    candidatos = [
        (quantidade, nome)
        for nome, quantidade in reprovacoes.items()
        if quantidade / len(da_vaga) >= TAXA_MINIMA
    ]
    if not candidatos:
        return None
    quantidade, criterio = max(candidatos)
    depois = vaga.model_copy(
        update={
            "competencias": [
                c.model_copy(update={"peso": round(c.peso * FATOR_DE_PESO, 4)})
                if c.nome == criterio
                else c
                for c in vaga.competencias
            ],
            "aprovada": False,
        }
    )
    if validar_criterios(depois):
        return None
    return PropostaAjuste(
        vaga_id=vaga.id,
        motivo=(
            f"{quantidade} de {len(da_vaga)} pessoas indicadas reprovaram na entrevista em "
            f"'{criterio}': a proposta dá mais peso a esse critério na nota"
        ),
        antes=vaga,
        depois=depois,
        resultado_avaliacao={
            "reprovacoes": float(quantidade),
            "entrevistas": float(len(da_vaga)),
            "taxa": round(quantidade / len(da_vaga), 4),
        },
    )


def aprovar(proposta: PropostaAjuste, responsavel: str) -> PropostaAjuste:
    """Só uma pessoa nomeada aprova. A proposta aprovada é uma cópia; a original não muda."""
    exigir_humano(responsavel)
    return proposta.model_copy(update={"aprovada": True})


def aplicar(proposta: PropostaAjuste) -> Vaga:
    """A vaga ajustada, para o RH editar e assinar de novo. Recusa proposta sem aprovação."""
    if not proposta.aprovada:
        raise AjusteNaoAprovado("o ajuste precisa da aprovação de uma pessoa antes de valer")
    return proposta.depois


def reverter(proposta: PropostaAjuste) -> Vaga:
    """A vaga de antes do ajuste. Repetir devolve a mesma vaga."""
    return proposta.antes
