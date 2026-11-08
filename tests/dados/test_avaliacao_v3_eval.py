"""Elegibilidade e pares no funil real; não mede precisão do modelo.

O funil atual só elimina falta comprovada. Caso ambíguo (dado ausente) segue adiante, e é a
análise ou a revisão que o manda para uma pessoa. Por isso o gabarito `pedir_humano` passa
pelo funil, e só `descartar` e `bloquear_contato` precisam sair, cada um pela sua regra.
"""

from datetime import date

import pytest

from backend.agente.regras import avaliar_requisitos
from backend.contratos.modelos import Candidato, Vaga
from backend.fontes.funil import Corte, RegraCorte, priorizar
from dados.avaliacao_v3 import construir

HOJE = date(2026, 11, 7)
REGRAS_DE_BLOQUEIO = {
    RegraCorte.OPT_OUT, RegraCorte.AUTORIZACAO_VENCIDA, RegraCorte.SEM_AUTORIZACAO,
}


def _priorizar(vaga: Vaga, candidatos: list[Candidato], limite: int = 20):
    """Chama o funil como o agente chama, guardando cada corte registrado."""
    cortes: list[Corte] = []
    escolhidos = priorizar(
        vaga, candidatos, limite, hoje=HOJE,
        avaliar_requisitos=avaliar_requisitos, registrar_corte=cortes.append,
    )
    return escolhidos, cortes


@pytest.mark.eval
def test_120_familias_indicaveis_da_prova_passam_pelo_funil():
    dados = construir()
    pessoas = [Candidato.model_validate(p) for p in dados["candidatos"]]
    familias = set()
    for vaga_dados in dados["vagas"]:
        vaga = Vaga.model_validate(vaga_dados)
        casos = [c for c in dados["gabarito"]["casos"] if c["particao"] == "prova"
                 and c["conta_independencia"] and c["vaga_id"] == vaga.id]
        candidatos = [pessoas[c["indice"]] for c in casos]
        esperados = {c["candidato_id"] for c in casos if c["resultado_esperado"] == "indicar"}
        encontrados, cortes = _priorizar(vaga, candidatos, limite=len(candidatos))
        ids = {p.id for p in encontrados}
        regra = {c.candidato_id: c.regra for c in cortes}
        assert esperados <= ids
        for caso in casos:
            esperado, pessoa = caso["resultado_esperado"], caso["candidato_id"]
            if esperado == "descartar":
                assert regra.get(pessoa) == RegraCorte.REQUISITO_NAO_ATENDIDO, pessoa
            elif esperado == "bloquear_contato":
                assert regra.get(pessoa) in REGRAS_DE_BLOQUEIO, pessoa
            elif esperado == "pedir_humano":
                assert pessoa in ids, pessoa
        familias.update(c["grupo_independencia"] for c in casos
                        if c["candidato_id"] in esperados)
    assert len(familias) == 120


@pytest.mark.eval
def test_pares_vies_preservam_elegibilidade_no_funil():
    dados = construir()
    vagas = {v["id"]: Vaga.model_validate(v) for v in dados["vagas"]}
    pares = {}
    for caso in dados["gabarito"]["casos"]:
        if caso["par_vies"]:
            pessoa = Candidato.model_validate(dados["candidatos"][caso["indice"]])
            resultado, _ = _priorizar(vagas[caso["vaga_id"]], [pessoa])
            pares.setdefault(caso["par_vies"], []).append([p.id for p in resultado])
    assert len(pares) == 12
    assert all(len(resultados) == 2 and resultados[0] == resultados[1] != []
               for resultados in pares.values())
