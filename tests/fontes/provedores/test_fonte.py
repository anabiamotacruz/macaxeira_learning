from datetime import date

import pytest

from backend.agente.persistencia import Repositorio, resumos_da_pessoa
from backend.contratos.erros import FonteIndisponivel
from backend.contratos.interfaces import FonteCandidatos
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.banco_talentos import BancoTalentos
from backend.fontes.provedores.cadeia import CadeiaProvedores, ModoDados
from backend.fontes.provedores.controles import OrcamentoProvedores
from backend.fontes.provedores.erros import MotivoTroca, UrlRecusada
from backend.fontes.provedores.fonte import FonteProvedores, SupressaoPorBanco, candidato_de_item
from backend.fontes.provedores.modelos import (
    CONTATO_NAO_PUBLICADO,
    ConfiancaDado,
    ConsultaProvedor,
    ContatoColetado,
    IdentidadeConsulta,
    ItemColetado,
    RespostaProvedor,
    SituacaoConsulta,
    id_externo,
    id_externo_de_email,
)
from tests.fontes.provedores.apoio import MOMENTO

EMPRESA = "empresa-a"
EMAIL = "pessoa@exemplo-ficticio.com.br"
HOJE = date(2026, 11, 7)


def item(url="https://site-ficticio.com.br/a", **campos) -> ItemColetado:
    return ItemColetado(
        **{
            "provedor": "bright_data",
            "fonte": "bright_data:pagina",
            "coletado_em": MOMENTO,
            "url": url,
            "confianca": ConfiancaDado.DECLARADO,
            "texto": "Perfil fictício de Python.",
            **campos,
        }
    )


class Provedor:
    """Responde por consulta: texto devolve os achados da busca, URL devolve a página."""

    nome = "bright_data"

    def __init__(self, busca=(), paginas=None):
        self.busca = list(busca)
        self.paginas = paginas or {}
        self.consultas = []

    def aceita(self, consulta):
        return consulta.identidade is None

    def custo_maximo(self, consulta):
        return 0.001

    def consultar(self, consulta):
        self.consultas.append(consulta)
        if consulta.texto is not None:
            return RespostaProvedor(itens=self.busca, custo_usd=0.001)
        resposta = self.paginas.get(consulta.url)
        if isinstance(resposta, Exception):
            raise resposta
        return RespostaProvedor(itens=[resposta] if resposta else [], custo_usd=0.001)


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def fonte_com(provedor, supressao=None, **opcoes) -> FonteProvedores:
    supressao = supressao or SemSupressao()
    modo = opcoes.pop("modo", ModoDados.REAIS)
    return FonteProvedores(
        CadeiaProvedores(
            [provedor] if provedor else [],
            supressao=supressao,
            orcamento=OrcamentoProvedores(limite_empresa_usd=10, limite_execucao_usd=10),
            dormir=lambda _: None,
            modo=modo,
        ),
        supressao=supressao,
        **opcoes,
    )


def test_cumpre_a_interface_de_fonte_de_candidatos():
    assert isinstance(fonte_com(Provedor()), FonteCandidatos)


def test_candidato_externo_entra_sem_autorizacao_e_com_procedencia():
    achado = item(
        nome="Pessoa Fictícia",
        atributos={"cargo": "engenheira"},
        contatos=[ContatoColetado(tipo="email", valor=EMAIL)],
    )
    candidato = candidato_de_item(EMPRESA, achado)
    assert candidato.empresa_id == EMPRESA
    assert candidato.autorizou_contato is False
    assert candidato.autorizacao_valida_ate is None
    assert candidato.estado == EstadoBanco.PENDENTE
    assert candidato.simulado is False
    assert candidato.fonte == "bright_data:pagina"
    assert candidato.origem == "https://site-ficticio.com.br/a"
    assert candidato.atualizado_em == MOMENTO.date()
    assert candidato.id == id_externo_de_email(EMAIL)
    assert candidato.atributos["provedor"] == "bright_data"
    assert candidato.atributos["confianca"] == "declarado"
    assert candidato.atributos["coletado_em"] == MOMENTO.isoformat()
    assert candidato.atributos["url"] == "https://site-ficticio.com.br/a"
    assert candidato.atributos["email"] == EMAIL
    assert candidato.atributos["contato_origem"] == CONTATO_NAO_PUBLICADO
    assert candidato.atributos["cargo"] == "engenheira"


def test_atributo_externo_nao_sobrepoe_a_procedencia():
    achado = item(atributos={"provedor": "falso", "confianca": "comprovado"})
    candidato = candidato_de_item(EMPRESA, achado)
    assert candidato.atributos["provedor"] == "bright_data"
    assert candidato.atributos["confianca"] == "declarado"


def test_sem_contato_nao_cria_marca_de_contato():
    candidato = candidato_de_item(EMPRESA, item())
    assert "contato_origem" not in candidato.atributos
    assert "email" not in candidato.atributos


def test_buscar_le_as_primeiras_paginas_e_mantem_o_trecho_das_demais():
    busca = [
        item(f"https://site-ficticio.com.br/{i}", fonte="bright_data:busca", texto=f"trecho {i}")
        for i in range(3)
    ]
    paginas = {busca[0].url: item(busca[0].url, texto="Página completa.")}
    provedor = Provedor(busca, paginas)
    candidatos = fonte_com(provedor, paginas_por_consulta=2).buscar(EMPRESA, "python")

    assert [c.perfil_texto for c in candidatos] == ["Página completa.", "trecho 1", "trecho 2"]
    assert [c.texto or c.url for c in provedor.consultas] == [
        "python",
        busca[0].url,
        busca[1].url,
    ]


def test_falha_ao_ler_uma_pagina_nao_perde_o_trecho():
    achado = item(fonte="bright_data:busca", texto="trecho")
    provedor = Provedor([achado], {achado.url: FonteIndisponivel("x")})
    assert [c.perfil_texto for c in fonte_com(provedor).buscar(EMPRESA, "python")] == ["trecho"]


def test_pagina_recusada_na_leitura_some_do_resultado():
    class Recusa(Provedor):
        def consultar(self, consulta):
            if consulta.url:
                raise UrlRecusada(MotivoTroca.DOMINIO_RECUSADO, 0.001)
            return super().consultar(consulta)

    achado = item(fonte="bright_data:busca", texto="trecho")
    assert fonte_com(Recusa([achado])).buscar(EMPRESA, "python") == []


def test_falha_de_todos_os_provedores_sobe_como_fonte_indisponivel():
    class Fora(Provedor):
        def consultar(self, consulta):
            raise FonteIndisponivel("fora")

    with pytest.raises(FonteIndisponivel):
        fonte_com(Fora()).buscar(EMPRESA, "python")


def test_consulta_recusada_devolve_lista_vazia():
    provedor = Provedor()
    assert fonte_com(provedor).buscar(EMPRESA, "python site:linkedin.com") == []
    assert provedor.consultas == []


def test_sem_provedores_devolve_vazio_e_o_estado_fica_visivel(caplog):
    fonte = fonte_com(None)
    assert fonte.buscar(EMPRESA, "python") == []
    assert fonte.estado().rotulo == "sem fontes externas"
    assert "sem fontes externas" in caplog.text


def test_modo_sintetico_usa_a_fonte_sintetica_e_nenhum_provedor():
    provedor = Provedor()
    sinteticos = FonteSimulada([candidato_simulado("s-1", EMPRESA, perfil_texto="python")])
    fonte = fonte_com(provedor, modo=ModoDados.SINTETICOS, fonte_sintetica=sinteticos)
    assert [c.id for c in fonte.buscar(EMPRESA, "python")] == ["s-1"]
    assert provedor.consultas == []
    assert fonte.estado().rotulo == "somente dados sintéticos"


def test_modo_sintetico_descarta_quem_nao_esta_marcado_como_simulado():
    real = candidato_simulado("r-1", EMPRESA, perfil_texto="python").model_copy(
        update={"simulado": False}
    )
    fonte = fonte_com(None, modo=ModoDados.SINTETICOS, fonte_sintetica=FonteSimulada([real]))
    assert fonte.buscar(EMPRESA, "python") == []


def test_modo_sintetico_sem_fonte_sintetica_devolve_vazio():
    assert fonte_com(None, modo=ModoDados.SINTETICOS).buscar(EMPRESA, "python") == []


def test_enriquecer_e_ler_pagina_devolvem_o_resultado_da_cadeia():
    fonte = fonte_com(Provedor(paginas={"https://site-ficticio.com.br/a": item()}))
    assert fonte.ler_pagina(EMPRESA, "https://site-ficticio.com.br/a").provedor == "bright_data"
    resultado = fonte.enriquecer(EMPRESA, IdentidadeConsulta(email=EMAIL))
    assert resultado.situacao == SituacaoConsulta.NAO_SUPORTADA


@pytest.fixture
def banco():
    banco = BancoTalentos(":memory:", hoje=HOJE)
    yield banco
    banco.fechar()


@pytest.fixture
def repositorio(tmp_path):
    return Repositorio(tmp_path / "agente.db")


def test_supressao_por_opt_out_no_banco(banco):
    banco.importar(EMPRESA, [registro("c-1")])
    supressao = SupressaoPorBanco(banco)
    assert not supressao.suprimida(EMPRESA, "c-1", None)
    banco.registrar_opt_out(EMPRESA, "c-1")
    assert supressao.suprimida(EMPRESA, "c-1", None)


def test_supressao_por_bloqueio_de_id_ou_email_no_repositorio(banco, repositorio):
    repositorio.registrar_bloqueios(EMPRESA, resumos_da_pessoa(EMPRESA, "c-2", EMAIL))
    supressao = SupressaoPorBanco(banco, bloqueios=[repositorio])
    assert supressao.suprimida(EMPRESA, "c-2", None)
    assert supressao.suprimida(EMPRESA, "qualquer", EMAIL.upper())
    assert not supressao.suprimida(EMPRESA, "qualquer", "outra@ficticio.com.br")
    assert not supressao.suprimida("empresa-b", "c-2", EMAIL)


def registro(candidato_id, **campos):
    return candidato_simulado(candidato_id, EMPRESA, **campos).model_dump()


def guardavel():
    return candidato_de_item(EMPRESA, item(contatos=[ContatoColetado(tipo="email", valor=EMAIL)]))


def test_guardar_entra_pendente_e_sem_autorizacao(banco):
    fonte = fonte_com(Provedor(), SupressaoPorBanco(banco), banco=banco)
    guardados = fonte.guardar(EMPRESA, [guardavel()])
    assert [c.estado for c in guardados] == [EstadoBanco.PENDENTE]
    assert banco.buscar(EMPRESA, "python") == []


def test_guardar_nao_traz_de_volta_quem_foi_removido(banco):
    fonte = fonte_com(Provedor(), SupressaoPorBanco(banco), banco=banco)
    candidato = guardavel()
    fonte.guardar(EMPRESA, [candidato])
    banco.remover(EMPRESA, candidato.id)

    assert fonte.guardar(EMPRESA, [candidato]) == []
    assert banco.obter(EMPRESA, candidato.id) is None


def test_guardar_nao_traz_de_volta_quem_saiu_por_email_com_outro_id(banco):
    banco.importar(EMPRESA, [registro("c-1", atributos={"email": EMAIL})])
    banco.registrar_opt_out(EMPRESA, "c-1")
    fonte = fonte_com(Provedor(), SupressaoPorBanco(banco), banco=banco)

    assert fonte.guardar(EMPRESA, [guardavel()]) == []
    assert banco.obter(EMPRESA, id_externo_de_email(EMAIL)) is None


def test_guardar_respeita_bloqueio_do_repositorio(banco, repositorio):
    candidato = guardavel()
    repositorio.registrar_bloqueios(EMPRESA, resumos_da_pessoa(EMPRESA, candidato.id, EMAIL))
    fonte = fonte_com(
        Provedor(), SupressaoPorBanco(banco, bloqueios=[repositorio]), banco=banco
    )
    assert fonte.guardar(EMPRESA, [candidato]) == []
    assert banco.obter(EMPRESA, candidato.id) is None


def test_guardar_sem_banco_e_erro_de_montagem():
    with pytest.raises(ValueError):
        fonte_com(Provedor()).guardar(EMPRESA, [guardavel()])


def test_ponta_a_ponta_quem_saiu_nao_e_consultado_de_novo(banco, repositorio):
    candidato = guardavel()
    repositorio.registrar_bloqueios(EMPRESA, resumos_da_pessoa(EMPRESA, candidato.id, EMAIL))
    provedor = Provedor()
    fonte = fonte_com(provedor, SupressaoPorBanco(banco, bloqueios=[repositorio]), banco=banco)
    resultado = fonte.enriquecer(EMPRESA, IdentidadeConsulta(email=EMAIL))
    assert resultado.situacao == SituacaoConsulta.SUPRIMIDO
    assert provedor.consultas == []


def test_id_do_candidato_e_o_mesmo_usado_na_supressao():
    achado = item(contatos=[ContatoColetado(tipo="email", valor=EMAIL)])
    assert candidato_de_item(EMPRESA, achado).id == id_externo(achado)


def test_pagina_de_busca_passa_para_a_cadeia():
    provedor = Provedor()
    fonte_com(provedor).buscar(EMPRESA, "python", pagina=3)
    assert provedor.consultas == [ConsultaProvedor(texto="python", pagina=3)]
