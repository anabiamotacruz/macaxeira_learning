"""Avaliações de elegibilidade e equidade do funil, com os 250 rótulos sintéticos.

O funil desta base só elimina falta comprovada: requisito sem dado segue adiante, para uma
pessoa decidir. Por isso a comparação com os rótulos é de contenção, não de igualdade: quem
atende tudo precisa aparecer, e quem tem falta comprovada não pode aparecer. O que fica no meio
é reserva, e sai registrado em `RegraCorte`.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.agente.regras import StatusRequisito, avaliar_requisitos
from backend.contratos.modelos import Candidato, EstadoBanco, Vaga
from backend.fontes.funil import Corte, RegraCorte, priorizar

pytestmark = pytest.mark.eval
PASTA = Path(__file__).resolve().parents[2] / "dados/sinteticos"
HOJE = date(2026, 11, 7)
SEM_LIMITE = 250


def _ler(nome: str):
    return json.loads((PASTA / nome).read_text())


@pytest.fixture(scope="module")
def conjunto():
    return (
        [Candidato.model_validate(p) for p in _ler("candidatos.json")],
        [Vaga.model_validate(v) for v in _ler("vagas.json")],
        _ler("respostas_certas.json")["casos"],
    )


def _da_empresa(perfis: list[Candidato], vaga: Vaga) -> list[Candidato]:
    """O funil recusa candidato de outra empresa antes de qualquer registro."""
    return [p for p in perfis if p.empresa_id == vaga.empresa_id]


def _rodar(vaga: Vaga, perfis: list[Candidato], limite: int = SEM_LIMITE):
    cortes: list[Corte] = []
    escolhidos = priorizar(
        vaga,
        _da_empresa(perfis, vaga),
        limite,
        hoje=HOJE,
        avaliar_requisitos=avaliar_requisitos,
        registrar_corte=cortes.append,
    )
    return escolhidos, cortes


def _mais_recente(registros: list) -> object:
    """O mesmo desempate do funil: data mais nova, depois fonte e origem."""
    return min(registros, key=lambda c: (-c.atualizado_em.toordinal(), c.fonte, c.origem))


def test_quem_atende_todos_os_requisitos_sempre_aparece(conjunto):
    """A única saída aceita para quem atende tudo é o perfil desatualizado, que vai a uma pessoa."""
    perfis, vagas, casos = conjunto
    for vaga in vagas:
        por_pessoa: dict[str, list] = {}
        for pessoa in _da_empresa(perfis, vaga):
            por_pessoa.setdefault(pessoa.id, []).append(pessoa)
        desatualizados = {
            pessoa_id
            for pessoa_id, registros in por_pessoa.items()
            if _mais_recente(registros).estado == EstadoBanco.DESATUALIZADO
        }
        esperados = {
            c["candidato_id"]
            for c in casos
            if c["vaga_id"] == vaga.id
            and c["autorizacao_para_vaga"] != "bloqueada"
            and all(r["estado"] == "atende" for r in c["requisitos"].values())
        } - desatualizados
        assert esperados, vaga.id
        escolhidos, cortes = _rodar(vaga, perfis)
        assert esperados <= {p.id for p in escolhidos}, vaga.id
        # Perfil desatualizado não é analisado. Quem adere à vaga vai para confirmação
        # humana; quem não adere vai para a reserva, que é a regra do funil.
        assert not (desatualizados & {p.id for p in escolhidos}), vaga.id
        regras = {c.regra for c in cortes if c.candidato_id in desatualizados}
        assert regras <= {
            RegraCorte.PERFIL_DESATUALIZADO,
            RegraCorte.RESERVA,
            RegraCorte.DUPLICATA,
        }, vaga.id


def test_falta_comprovada_de_requisito_nunca_passa(conjunto):
    perfis, vagas, _ = conjunto
    for vaga in vagas:
        escolhidos, _ = _rodar(vaga, perfis)
        for pessoa in escolhidos:
            status = avaliar_requisitos(vaga, pessoa)
            assert StatusRequisito.NAO_ATENDE not in status.values(), f"{vaga.id}/{pessoa.id}"


def test_escolhido_tem_autorizacao_valida_e_nao_pediu_saida(conjunto):
    perfis, vagas, _ = conjunto
    for vaga in vagas:
        escolhidos, _ = _rodar(vaga, perfis)
        for pessoa in escolhidos:
            assert pessoa.empresa_id == vaga.empresa_id
            assert not pessoa.opt_out
            assert pessoa.autorizou_contato
            assert pessoa.autorizacao_valida_ate is not None
            assert pessoa.autorizacao_valida_ate >= HOJE


def test_ninguem_sai_do_funil_sem_regra_registrada(conjunto):
    """O conjunto traz registros repetidos do mesmo id, então a conta é por id, não por registro."""
    perfis, vagas, _ = conjunto
    for vaga in vagas:
        escolhidos, cortes = _rodar(vaga, perfis)
        da_empresa = {p.id for p in _da_empresa(perfis, vaga)}
        fora = da_empresa - {p.id for p in escolhidos}
        assert fora <= {c.candidato_id for c in cortes}, vaga.id
        assert {c.candidato_id for c in cortes} <= da_empresa, vaga.id
        for corte in cortes:
            assert corte.empresa_id == vaga.empresa_id
            assert corte.vaga_id == vaga.id
            assert RegraCorte(corte.regra)
            assert corte.motivo.strip()


def test_limite_corta_por_posicao_e_nao_por_merito_oculto(conjunto):
    """Quem cabia e deixou de caber sai por posição. Nunca por requisito ou autorização."""
    perfis, vagas, _ = conjunto
    por_posicao = {RegraCorte.FORA_DO_LIMITE, RegraCorte.RESERVA, RegraCorte.DUPLICATA}
    for vaga in vagas:
        completos, _ = _rodar(vaga, perfis)
        if len(completos) < 2:
            continue
        reduzidos, cortes = _rodar(vaga, perfis, limite=1)
        assert [p.id for p in reduzidos] == [completos[0].id], vaga.id
        perdidos = {p.id for p in completos[1:]}
        regras = {c.regra for c in cortes if c.candidato_id in perdidos}
        assert regras, vaga.id
        assert regras <= por_posicao, vaga.id


def test_nome_e_genero_nao_mudam_a_ordem(conjunto):
    perfis, vagas, _ = conjunto
    alterados = []
    for indice, perfil in enumerate(perfis):
        copia = perfil.model_copy(deep=True)
        copia.nome = f"SQL Docker Pessoa Fictícia {indice}"
        copia.atributos["genero"] = "feminino" if indice % 2 else "masculino"
        alterados.append(copia)
    for vaga in vagas:
        antes, _ = _rodar(vaga, perfis)
        depois, _ = _rodar(vaga, list(reversed(alterados)))
        assert [p.id for p in antes] == [p.id for p in depois], vaga.id
