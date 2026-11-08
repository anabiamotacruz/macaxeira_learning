"""E-mail publicado consultado na EnvoAPI, só para quem o agente indicou (pedido de 8/11).

Perfis fictícios, como a LinkdAPI os entrega: fonte externa, sem contato e com o usuário do
LinkedIn em `atributos`. O buscador é falso: nenhum teste usa rede.
"""

from backend.agente.contato_publicado import ContatoPorEmpresa
from backend.agente.fluxo import FluxoVaga
from backend.agente.mandato import Politica
from backend.agente.montagem import priorizador_do_funil
from backend.agente.persistencia import Repositorio
from backend.contratos.erros import FonteIndisponivel
from backend.contratos.modelos import RespostaCandidato, TipoDecisao, TipoResposta
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import RevisorSemRessalva, vaga_exemplo
from tests.agente.test_fluxo_contato_publicado import Pecas, externo

EMAIL = "pessoa@exemplo.invalid"
USUARIO = "pessoa-ficticia"
ORIGEM_LINKEDIN = f"https://www.linkedin.com/in/{USUARIO}/"


def do_linkedin(candidato_id: str = "ext", **campos):
    """Como `candidato_de_item` entrega um item da LinkdAPI: dado de perfil inferido, sem e-mail."""
    atributos = {
        "python": "sim",
        "usuario_linkedin": USUARIO,
        "provedor": "linkdapi",
        "confianca": "inferido",
    }
    return externo(
        candidato_id,
        fonte="linkdapi:people_search",
        origem="linkdapi:people_search",
        atributos=atributos | campos.pop("atributos", {}),
        **campos,
    )


class BuscadorFalso:
    def __init__(self, resposta: list[str] | Exception | None = None) -> None:
        self.resposta = [EMAIL] if resposta is None else resposta
        self.consultas: list[str] = []

    def emails_publicados(self, usuario_ou_url: str) -> list[str]:
        self.consultas.append(usuario_ou_url)
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return list(self.resposta)


class PecasEnvo(Pecas):
    def __init__(self, tmp_path, candidatos, buscador: BuscadorFalso | None, **opcoes) -> None:
        super().__init__(tmp_path, candidatos, **opcoes)
        self.buscador = buscador
        self.contato = None if buscador is None else ContatoPorEmpresa(buscador)

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
            buscador_contato=self.contato,
        )


def _eventos(fluxo: FluxoVaga, candidato_id: str = "ext") -> list[str]:
    return [e.mensagem for e in fluxo.eventos if e.candidato_id == candidato_id]


def test_indicado_sem_email_com_usuario_e_chave_consulta_uma_vez_e_o_convite_sai(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)

    fluxo = pecas.rodar()
    fluxo.continuar()

    assert fluxo._ultimas_decisoes()["ext"].tipo is TipoDecisao.INDICAR
    assert buscador.consultas == [USUARIO]
    [convite] = pecas.convites_para("ext")
    assert ORIGEM_LINKEDIN in convite.mensagem
    assert "Por que você recebeu" in convite.mensagem
    assert "Não quero mais contato" in convite.mensagem
    assert convite.simulado
    assert not any("contato_nao_publicado" in m for m in _eventos(fluxo))
    assert any("EnvoAPI" in m for m in _eventos(fluxo))


def test_o_resultado_fica_guardado_por_empresa_e_outra_vaga_nao_paga_de_novo(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)

    pecas.rodar()
    pecas.rodar(vaga_exemplo(id="v2"))

    assert buscador.consultas == [USUARIO]
    assert {c.vaga_id for c in pecas.convites_para("ext")} == {"v1", "v2"}


def test_o_aceite_usa_o_email_guardado_sem_nova_consulta(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)
    fluxo = pecas.rodar()
    [convite] = pecas.convites_para("ext")

    fluxo.registrar_resposta(RespostaCandidato(convite_id=convite.id, tipo=TipoResposta.ACEITE))

    assert buscador.consultas == [USUARIO]
    assert pecas.banco.obter("empresa-a", "ext").autorizou_contato


def test_descartado_nao_e_consultado(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)
    pecas.analisador.notas = {"ext": 0.0}

    fluxo = pecas.rodar()

    assert fluxo._ultimas_decisoes()["ext"].tipo is not TipoDecisao.INDICAR
    assert buscador.consultas == []


def test_opt_out_nao_e_consultado(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin(opt_out=True)], buscador)

    pecas.rodar()

    assert buscador.consultas == []
    assert pecas.convites_para("ext") == []


def test_bloqueio_de_opt_out_da_empresa_corta_antes_da_consulta(tmp_path):
    """O opt-out vem dos bloqueios da empresa, conferidos por código antes de qualquer custo."""
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)
    fluxo = pecas.fluxo()
    fluxo._tem_opt_out = lambda candidato: True
    fluxo.iniciar()

    fluxo.assinar_mandato(
        "Pessoa Recrutadora",
        5.0,
        Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=0),
    )

    assert buscador.consultas == []
    assert pecas.convites_para("ext") == []


def test_404_sem_email_nao_convida_e_registra_o_motivo(tmp_path):
    buscador = BuscadorFalso([])
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)

    fluxo = pecas.rodar()
    fluxo.continuar()

    assert buscador.consultas == [USUARIO]
    assert pecas.convites_para("ext") == []
    eventos = _eventos(fluxo)
    assert sum("contato_nao_publicado" in m for m in eventos) == 1
    assert any("nenhum e-mail publicado" in m for m in eventos)


def test_falha_da_envoapi_nao_para_a_vaga_nem_gera_nova_consulta(tmp_path):
    buscador = BuscadorFalso(FonteIndisponivel("envoapi: limite"))
    pecas = PecasEnvo(tmp_path, [do_linkedin()], buscador)

    fluxo = pecas.rodar()
    fluxo.continuar()

    assert buscador.consultas == [USUARIO]
    assert pecas.convites_para("ext") == []
    assert any("FonteIndisponivel" in m for m in _eventos(fluxo))


def test_sem_chave_nao_ha_consulta_e_fica_como_antes(tmp_path):
    pecas = PecasEnvo(tmp_path, [do_linkedin()], None)

    fluxo = pecas.rodar()

    assert pecas.convites_para("ext") == []
    assert any("contato_nao_publicado" in m for m in _eventos(fluxo))


def test_sem_usuario_do_linkedin_nao_ha_consulta(tmp_path):
    buscador = BuscadorFalso()
    sem_usuario = do_linkedin(atributos={"usuario_linkedin": "nome com espaço"})
    pecas = PecasEnvo(tmp_path, [sem_usuario], buscador)

    pecas.rodar()

    assert buscador.consultas == []


def test_quem_ja_publicou_email_na_fonte_nao_e_consultado(tmp_path):
    buscador = BuscadorFalso()
    pecas = PecasEnvo(tmp_path, [externo()], buscador)

    pecas.rodar()

    assert buscador.consultas == []
    assert len(pecas.convites_para("ext")) == 1


def test_atributo_de_email_envo_vindo_da_fonte_e_ignorado(tmp_path):
    """Só o agente grava o e-mail da EnvoAPI: a fonte não consegue fingir que ele existe."""
    from backend.agente.contato_publicado import EMAIL_PUBLICADO_ENVO

    forjado = do_linkedin(atributos={EMAIL_PUBLICADO_ENVO: EMAIL})
    pecas = PecasEnvo(tmp_path, [forjado], None)

    pecas.rodar()

    assert pecas.convites_para("ext") == []


CHAVE_FALSA = "chave-sintetica-envoapi-0123456789"


def _busca_simulada(_ambiente):
    from backend.contratos.simulacoes import FonteSimulada

    return lambda banco, repositorio: FonteSimulada([])


def test_montagem_com_busca_real_e_chave_injeta_o_buscador(tmp_path):
    from backend.agente.montagem import montar_servico

    servico = montar_servico(
        tmp_path / "a.db",
        ambiente={"AGENTE_BUSCA_REAL": "1", "ENVO_API_KEY": CHAVE_FALSA},
        criar_busca=_busca_simulada,
    )

    contato = servico._dependencias.buscador_contato
    assert isinstance(contato, ContatoPorEmpresa)
    assert CHAVE_FALSA not in repr(contato)
    assert CHAVE_FALSA not in repr(servico._dependencias)


def test_montagem_sem_chave_nao_injeta_o_buscador(tmp_path):
    from backend.agente.montagem import montar_servico

    servico = montar_servico(
        tmp_path / "a.db", ambiente={"AGENTE_BUSCA_REAL": "1"}, criar_busca=_busca_simulada
    )

    assert servico._dependencias.buscador_contato is None


def test_demo_sintetica_nunca_chama_a_envoapi_mesmo_com_chave(tmp_path, monkeypatch):
    from backend.agente.montagem import montar_demo, montar_servico

    monkeypatch.setenv("ENVO_API_KEY", CHAVE_FALSA)

    assert montar_demo(tmp_path / "a.db")._dependencias.buscador_contato is None
    servico = montar_servico(tmp_path / "b.db", ambiente={"ENVO_API_KEY": CHAVE_FALSA})
    assert servico._dependencias.buscador_contato is None
