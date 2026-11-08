"""Quem vem da busca real é analisado e convidado só pelo contato que publicou (decisão de 8/11).

Os perfis são fictícios e marcados como de fonte externa (`simulado=False`), como a Frente 2 os
entrega. Nenhum teste usa rede nem modelo de verdade.
"""

from datetime import date
from pathlib import Path

from backend.agente.fluxo import EstadoFluxo, FluxoVaga
from backend.agente.mandato import Politica
from backend.agente.montagem import priorizador_do_funil
from backend.agente.persistencia import Repositorio
from backend.contato.prompts import AVISO_SIMULACAO, PALAVRA_SAIDA
from backend.contratos.modelos import (
    EstadoBanco,
    RespostaCandidato,
    TipoDecisao,
    TipoResposta,
)
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
)
from backend.fontes.provedores.modelos import CONTATO_NAO_PUBLICADO
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import (
    AnalisadorComEvidencias,
    Relogio,
    RevisorSemRessalva,
    candidato_exemplo,
    vaga_exemplo,
)

EMPRESA = "empresa-a"
ORIGEM = "https://pessoa.exemplo.invalid/sobre"
EMAIL = "pessoa@exemplo.invalid"


def externo(candidato_id: str = "ext", **campos):
    atributos = campos.pop("atributos", {"python": "sim", "email": EMAIL})
    dados = {
        "fonte": "site_publico",
        "simulado": False,
        "origem": ORIGEM,
        "autorizacao_valida_ate": None,
        "autorizou_contato": False,
        "estado": EstadoBanco.PENDENTE,
        "atributos": atributos,
    }
    dados.update(campos)
    return candidato_exemplo(candidato_id, **dados)


class Pecas:
    """Fluxo com o funil real e simulações nas demais peças. `fluxo()` reabre o mesmo banco."""

    def __init__(self, tmp_path: Path, candidatos, *, banco=None) -> None:
        self.caminho = tmp_path / "agente.db"
        self.fonte = FonteSimulada(candidatos)
        self.banco = BancoTalentosSimulado() if banco is None else banco
        self.analisador = AnalisadorComEvidencias()
        self.mensageiro = MensageiroSimulado()
        self.destino = ClienteNaraSimulado()
        self.relogio = Relogio()

    def fluxo(self, vaga=None) -> FluxoVaga:
        return FluxoVaga(
            vaga or vaga_exemplo(),
            repositorio=Repositorio(self.caminho),
            banco=self.banco,
            fontes=[self.fonte],
            analisador=self.analisador,
            revisor=RevisorSemRessalva(),
            mensageiro=self.mensageiro,
            destino=self.destino,
            relogio=self.relogio,
            medidor_gasto=lambda: 0.0,
            priorizador=priorizador_do_funil(),
            resiliencia=Resiliencia(dormir=lambda _: None),
        )

    def rodar(self, vaga=None) -> FluxoVaga:
        fluxo = self.fluxo(vaga)
        fluxo.iniciar()
        politica = Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=0)
        fluxo.assinar_mandato("Pessoa Recrutadora", 5.0, politica)
        return fluxo

    def convites_para(self, candidato_id: str):
        return [c for c in self.mensageiro.enviados.values() if c.candidato_id == candidato_id]


def _decisao(fluxo: FluxoVaga, candidato_id: str):
    return fluxo._ultimas_decisoes()[candidato_id]


def test_externo_sem_autorizacao_e_analisado_e_indicado(tmp_path):
    pecas = Pecas(tmp_path, [externo()])

    fluxo = pecas.rodar()

    assert "ext" in pecas.analisador.analisados
    assert _decisao(fluxo, "ext").tipo is TipoDecisao.INDICAR


def test_com_email_publicado_o_convite_sai_com_origem_e_saida(tmp_path):
    pecas = Pecas(tmp_path, [externo()])

    fluxo = pecas.rodar()

    [convite] = pecas.convites_para("ext")
    assert convite.canal == "email"
    assert convite.simulado, "o envio é pelo mensageiro simulado e aparece como simulação"
    assert ORIGEM in convite.mensagem
    assert "Por que você recebeu" in convite.mensagem
    assert PALAVRA_SAIDA in convite.mensagem
    assert "Não quero mais contato" in convite.mensagem
    assert AVISO_SIMULACAO in convite.mensagem
    assert fluxo.estado is EstadoFluxo.CONVIDANDO


def test_sem_email_publicado_nao_ha_convite_e_o_motivo_fica_registrado(tmp_path):
    pecas = Pecas(tmp_path, [externo(atributos={"python": "sim"})])

    fluxo = pecas.rodar()
    fluxo.continuar()

    assert _decisao(fluxo, "ext").tipo is TipoDecisao.INDICAR
    assert pecas.convites_para("ext") == []
    assert all(r.convite.candidato_id != "ext" for r in fluxo.convites())
    motivos = [e.mensagem for e in fluxo.eventos if e.candidato_id == "ext"]
    assert sum("contato_nao_publicado" in m for m in motivos) == 1


def test_email_inferido_nunca_e_usado(tmp_path):
    inferido = externo(
        atributos={"python": "sim", "email": EMAIL, "contato_origem": CONTATO_NAO_PUBLICADO}
    )
    pecas = Pecas(tmp_path, [inferido])

    fluxo = pecas.rodar()

    assert pecas.convites_para("ext") == []
    assert all(EMAIL not in c.mensagem for c in pecas.mensageiro.enviados.values())
    assert any(
        "contato_nao_publicado" in e.mensagem for e in fluxo.eventos if e.candidato_id == "ext"
    )


def test_opt_out_de_quem_nao_tinha_autorizacao_vale_para_outra_vaga(tmp_path):
    pecas = Pecas(tmp_path, [externo()])
    fluxo = pecas.rodar()
    [convite] = pecas.convites_para("ext")

    fluxo.registrar_resposta(RespostaCandidato(convite_id=convite.id, tipo=TipoResposta.OPT_OUT))

    assert all(r.estado == "encerrado" for r in fluxo.convites() if r.convite.candidato_id == "ext")
    pecas.analisador.analisados.clear()
    outra = pecas.rodar(vaga_exemplo(id="v2"))
    assert "ext" not in pecas.analisador.analisados
    assert _decisao(outra, "ext").regra == "funil:opt_out"
    assert [c.vaga_id for c in pecas.convites_para("ext")] == ["v1"]


def test_opt_out_em_qualquer_fonte_corta_antes_do_modelo(tmp_path):
    saiu = externo(fonte="github", origem="https://github.invalid/ext", opt_out=True)
    pecas = Pecas(tmp_path, [externo(), saiu])

    fluxo = pecas.rodar()

    assert "ext" not in pecas.analisador.analisados
    assert _decisao(fluxo, "ext").regra == "funil:opt_out"
    assert pecas.convites_para("ext") == []


def test_autorizacao_vencida_no_banco_continua_cortando(tmp_path):
    banco = BancoTalentosSimulado()
    banco.importar(EMPRESA, [{"id": "ext", "perfil_texto": "Perfil fictício"}])
    banco.registrar_autorizacao(EMPRESA, "ext", date(2026, 11, 1))
    pecas = Pecas(tmp_path, [externo()], banco=banco)

    fluxo = pecas.rodar()

    assert "ext" not in pecas.analisador.analisados
    decisao = _decisao(fluxo, "ext")
    assert decisao.tipo is TipoDecisao.DESCARTAR
    assert "vencida" in decisao.motivo
    assert pecas.convites_para("ext") == []


def test_quem_tem_autorizacao_segue_com_o_convite_de_sempre(tmp_path):
    pecas = Pecas(tmp_path, [candidato_exemplo("banco", atributos={"python": "sim"})])

    pecas.rodar()

    [convite] = pecas.convites_para("banco")
    assert "Por que você recebeu" not in convite.mensagem


ORIGEM_DO_ACEITE = "aceite do convite enviado ao contato publicado"


def _responder(fluxo: FluxoVaga, pecas: Pecas, tipo: TipoResposta) -> None:
    [convite] = pecas.convites_para("ext")
    fluxo.registrar_resposta(RespostaCandidato(convite_id=convite.id, tipo=tipo))


def test_aceite_de_quem_nao_tinha_autorizacao_registra_a_autorizacao_e_entrega(tmp_path):
    pecas = Pecas(tmp_path, [externo()])
    fluxo = pecas.rodar()

    _responder(fluxo, pecas, TipoResposta.ACEITE)

    registro = pecas.banco.obter(EMPRESA, "ext")
    assert registro is not None
    assert registro.autorizou_contato
    assert registro.estado is EstadoBanco.ATIVO
    assert registro.autorizacao_valida_ate == date(2027, 11, 7)
    assert [p.candidato_id for p in pecas.destino.entregues.values()] == ["ext"]
    eventos = [e.mensagem for e in fluxo.eventos if e.candidato_id == "ext"]
    assert sum(ORIGEM_DO_ACEITE in m for m in eventos) == 1
    assert not any("entrega cancelada" in m for m in eventos)


def test_recusa_nao_registra_autorizacao_nem_entrega(tmp_path):
    pecas = Pecas(tmp_path, [externo()])
    fluxo = pecas.rodar()

    _responder(fluxo, pecas, TipoResposta.RECUSA)

    assert pecas.banco.obter(EMPRESA, "ext") is None
    assert pecas.destino.entregues == {}


def test_opt_out_nao_registra_autorizacao_e_continua_permanente(tmp_path):
    pecas = Pecas(tmp_path, [externo()])
    fluxo = pecas.rodar()

    _responder(fluxo, pecas, TipoResposta.OPT_OUT)
    _responder(fluxo, pecas, TipoResposta.ACEITE)

    assert pecas.banco.obter(EMPRESA, "ext") is None
    assert pecas.destino.entregues == {}
    outra = pecas.rodar(vaga_exemplo(id="v2"))
    assert _decisao(outra, "ext").regra == "funil:opt_out"


def _situacao_de(fluxo: FluxoVaga, candidato_id: str):
    return next(c for c, _, _ in fluxo.situacao_candidatos() if c.id == candidato_id)


def test_situacao_traz_link_do_linkedin_e_email_publicado_da_envoapi(tmp_path):
    pecas = Pecas(tmp_path, [externo(atributos={"python": "sim", "usuario_linkedin": "ana-souza"})])
    fluxo = pecas.rodar()
    fluxo._mudar(lambda p: p.contatos_envo.update({"ext": "ana@exemplo.invalid"}))

    atributos = _situacao_de(fluxo, "ext").atributos

    assert atributos["usuario_linkedin"] == "ana-souza"
    assert atributos["perfil_linkedin"] == "https://www.linkedin.com/in/ana-souza/"
    assert atributos["email_publicado"] == "ana@exemplo.invalid"


def test_situacao_sem_contato_nao_inventa_campos_e_recusa_usuario_estranho(tmp_path):
    pecas = Pecas(tmp_path, [externo(atributos={"python": "sim", "usuario_linkedin": "x/../y?z"})])
    fluxo = pecas.rodar()

    atributos = _situacao_de(fluxo, "ext").atributos

    assert "perfil_linkedin" not in atributos
    assert "email_publicado" not in atributos
