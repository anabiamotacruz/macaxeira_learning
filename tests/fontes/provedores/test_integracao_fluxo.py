"""A fonte externa dentro do fluxo real, com transporte simulado e dados sintéticos."""

import logging
from pathlib import Path

import httpx2
import pytest

from backend.agente.fluxo import FluxoVaga
from backend.agente.persistencia import Repositorio
from backend.contratos.modelos import Politica
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
)
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.fonte import FonteProvedores
from backend.fontes.provedores.modelos import IdentidadeConsulta
from backend.fontes.provedores.transporte import TransporteHttp
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import (
    AnalisadorComEvidencias,
    Relogio,
    RevisorSemRessalva,
    candidato_exemplo,
    vaga_exemplo,
)
from tests.fontes.provedores.apoio import (
    CHAVE_PDL,
    TOKEN_BRIGHT,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

AMBIENTE = {
    "BRIGHTDATA_API_TOKEN": TOKEN_BRIGHT,
    "BRIGHTDATA_ZONA_WEB": "zona_web",
    "BRIGHTDATA_ZONA_BUSCA": "zona_busca",
    "PDL_API_KEY": CHAVE_PDL,
}
EMAIL = "pessoa@exemplo-ficticio.com.br"


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def fonte_externa(transporte) -> FonteProvedores:
    fonte = montar_fonte_externa(
        AMBIENTE,
        transporte=transporte,
        supressao=SemSupressao(),
        relogio=relogio_fixo,
        resolver=resolver_publico,
        dormir=lambda _: None,
    )
    return fonte


def rodar(
    tmp_path: Path, fontes: list
) -> tuple[FluxoVaga, AnalisadorComEvidencias, MensageiroSimulado]:
    analisador = AnalisadorComEvidencias()
    mensageiro = MensageiroSimulado()
    fluxo = FluxoVaga(
        vaga_exemplo(),
        repositorio=Repositorio(tmp_path / "agente.db"),
        banco=BancoTalentosSimulado(),
        fontes=fontes,
        analisador=analisador,
        revisor=RevisorSemRessalva(),
        mensageiro=mensageiro,
        destino=ClienteNaraSimulado(),
        relogio=Relogio(),
        medidor_gasto=lambda: 0.0,
        resiliencia=Resiliencia(dormir=lambda _: None),
    )
    fluxo.iniciar()
    fluxo.assinar_mandato(
        "Pessoa Recrutadora",
        5.0,
        Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=0),
    )
    return fluxo, analisador, mensageiro



class TransporteFora(TransporteSimulado):
    def enviar(self, pedido):
        self.pedidos.append(pedido)
        raise ConnectionError("queda")


def test_provedores_fora_do_ar_deixam_o_fluxo_com_cobertura_parcial(tmp_path):
    transporte = TransporteFora()
    outra = FonteSimulada([candidato_exemplo("c1"), candidato_exemplo("c2")])
    fluxo, analisador, _ = rodar(tmp_path, [fonte_externa(transporte), outra])

    assert transporte.pedidos
    assert sorted(analisador.analisados) == ["c1", "c2"]
    cobertura = [e for e in fluxo.eventos if e.etapa == "cobertura"]
    assert len(cobertura) == 1
    assert "FonteProvedores" in cobertura[0].mensagem


def test_pessoa_vinda_de_provedor_nao_vai_ao_modelo_nem_recebe_convite(tmp_path):
    busca = resposta_json(
        {
            "organic": [
                {
                    "global_rank": 1,
                    "title": "Portfólio fictício",
                    "link": "https://site-ficticio.com.br/",
                    "description": "Cinco anos com Python",
                }
            ]
        }
    )
    pagina = resposta_json(
        {
            "status_code": 200,
            "headers": {"content-type": "text/html"},
            "body": "<p>Cinco anos com Python. Liderou APIs em produção.</p>",
        }
    )
    transporte = TransporteSimulado(busca, pagina)
    _, analisador, mensageiro = rodar(tmp_path, [fonte_externa(transporte)])

    assert len(transporte.pedidos) == 2
    assert analisador.analisados == []
    assert mensageiro.enviados == {}


def test_log_do_cliente_http_real_nao_recebe_chave_nem_dado_pessoal(caplog):
    caplog.set_level(logging.DEBUG)
    visto = []

    def tratar(requisicao: httpx2.Request) -> httpx2.Response:
        visto.append(requisicao)
        return httpx2.Response(404, json={"status": 404})

    transporte = TransporteHttp(httpx2.Client(transport=httpx2.MockTransport(tratar)))
    fonte = montar_fonte_externa(
        {"PDL_API_KEY": CHAVE_PDL},
        transporte=transporte,
        supressao=SemSupressao(),
        relogio=relogio_fixo,
    )
    fonte.enriquecer("empresa-a", IdentidadeConsulta(email=EMAIL))

    assert visto[0].headers["x-api-key"] == CHAVE_PDL
    assert EMAIL not in str(visto[0].url)
    assert CHAVE_PDL not in str(visto[0].url)
    assert EMAIL not in caplog.text
    assert CHAVE_PDL not in caplog.text


@pytest.mark.parametrize("consulta", ["a" * 301, "   "])
def test_consulta_fora_do_formato_nao_quebra_a_busca(consulta, caplog):
    transporte = TransporteSimulado()
    assert fonte_externa(transporte).buscar("empresa-a", consulta) == []
    assert transporte.pedidos == []
    assert "a" * 301 not in caplog.text
