"""Identificadores até o modelo, marcador forjado e custo do texto. Dados sintéticos, sem rede."""

import subprocess
import sys
import textwrap
import time
from datetime import timedelta

import pytest

from backend.agente.neutralizacao import MARCADOR, MAXIMO_DE_CARACTERES_DO_PERFIL
from backend.agente.prompts import como_dado
from backend.contratos.modelos import Candidato
from backend.fontes.analisador import preparar_perfil
from backend.fontes.anonimizador import Pseudonimizador
from tests.agente.apoio import AGORA

EMP = "empresa-a"
HOJE = AGORA.date()


def cand(texto: str, nome: str = "Ana Beatriz Lima", cid: str = "c1", **campos) -> Candidato:
    dados = dict(
        id=cid,
        empresa_id=EMP,
        nome=nome,
        fonte="rede_simulada",
        simulado=True,
        origem="planilha",
        atualizado_em=HOJE,
        autorizacao_valida_ate=HOJE + timedelta(days=100),
        estado="ativo",
        perfil_texto=texto,
        atributos={"python": "sim"},
        historico=[],
        autorizou_contato=True,
    )
    dados.update(campos)
    return Candidato(**dados)


def _rodar_com_limite(codigo: str, limite: int) -> tuple[float, int | None, str, str]:
    """Em processo próprio: `re` segura o GIL, e uma thread não conseguiria interromper."""
    inicio = time.time()
    try:
        saida = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(codigo)],
            capture_output=True,
            text=True,
            timeout=limite,
            cwd=".",
            env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return float("inf"), None, "", ""
    return time.time() - inicio, saida.returncode, saida.stdout[-400:], saida.stderr[-300:]


# ---------- A-1: identificadores comuns até o modelo ----------
@pytest.mark.parametrize(
    ("texto", "proibido"),
    [
        ("Portfólio em analima.ninja/perfil.", "analima"),
        ("Links: linktr.ee/analima92 e bit.ly/ana92.", "analima92"),
        ("Blog: analima.us", "analima"),
        ("E-mail: lima92 @ gmail . com", "lima92"),
        ("Meu GitHub é analima92, sigam.", "analima92"),
        ("github analima92 tem meus projetos", "analima92"),
        ("Telefone 415-555-0100.", "555-0100"),
        ("Whats: 8 1 9 8 8 8 8 7 7 7 7", "8 8 8 8"),
        ("Documento 12.345.678-9", "12.345.678-9"),
        ("Referência: Gerente Carlos Souza pode confirmar.", "Carlos Souza"),
        ("Trabalhei com a Engenheira Carla Mendes Dias.", "Carla Mendes"),
        ("Referência: CARLOS ALBERTO SOUZA, gerente.", "CARLOS ALBERTO"),
        ("Moro na R. das Flores, 123, em Recife.", "Flores, 123"),
        ("Experiência: Nubank (2019-2021), Stone (2021-2024).", "Nubank"),
        ("A n a  L i m a é meu nome", "L i m a"),
        ("Аna Lima tem CV", "Аna"),
        ("An\U000e0001a Lima fez APIs", "An\U000e0001a"),
        ("An︀a Li︀ma fez APIs", "An︀a"),
    ],
)
def test_L1_identificador_nao_chega_ao_modelo(texto, proibido):
    resultado = preparar_perfil(cand(texto, atributos={}), pseudonimizador=Pseudonimizador())
    assert proibido not in resultado.texto, resultado.texto


def test_L2_link_conhecido_da_pessoa_e_retirado():
    candidato = cand(
        "Veja meus trabalhos em analima.ninja e https://analima.ninja/cv.",
        atributos={"links": "https://analima.ninja", "portfolio": "https://analima.ninja"},
        origem="https://analima.ninja",
    )
    resultado = preparar_perfil(candidato, pseudonimizador=Pseudonimizador())
    assert "analima" not in resultado.texto, resultado.texto


# ---------- A-1: medição de vazamento ----------
META_VAZAMENTO_DIRETO = 0.0
"""Nome, contato, documento, endereço e link da própria pessoa: nada pode passar."""
META_VAZAMENTO_INDIRETO = 0.20
"""Terceiros, empregadores e instituições: por regra, sem modelo, parte passa. É o teto aceito."""
META_RETENCAO_TECNICA = 0.95
"""Termos técnicos que precisam continuar no texto, ou a análise perde a evidência."""

CURRICULOS_SINTETICOS = [
    {
        "nome": "Zulmira Ficticia Prado",
        "atributos": {"email": "zulmira.prado@example.invalid", "site": "https://zuprado.example"},
        "texto": (
            "Zulmira Ficticia Prado. Contato: zulmira.prado@example.invalid, (81) 98888-7777. "
            "Site zuprado.example/cv. CPF 123.456.789-00. Moro na Rua das Acacias, 45. "
            "Trabalhei na Empresa Quantica Sistemas com Python e Kubernetes. "
            "Formada na Universidade Federal Ficticia. Referência: gestor Paulo Teixeira Neto."
        ),
        "diretos": [
            "Zulmira",
            "Prado",
            "zulmira.prado",
            "98888-7777",
            "zuprado",
            "123.456.789-00",
            "Acacias",
        ],
        "indiretos": ["Quantica", "Universidade Federal Ficticia", "Paulo Teixeira"],
        "tecnicos": ["Python", "Kubernetes"],
    },
    {
        "nome": "Otavio Lemos Barreto",
        "atributos": {"github": "https://github.com/otaviolb77"},
        "texto": (
            "OTAVIO LEMOS BARRETO\n"
            "Meu GitHub é otaviolb77 e o blog fica em otaviolb.ninja. "
            "E-mail: otavio77 @ gmail . com. "
            "Whats 8 1 9 9 9 9 9 0 0 0 1. RG 12.345.678-9. Moro na Av. Atlantica, 900. "
            "Experiência: Lumen Dados (2018-2020), Vetor Pagamentos (2020-2024). "
            "Desenvolvi APIs em FastAPI, PostgreSQL e Redis na AWS."
        ),
        "diretos": [
            "OTAVIO",
            "BARRETO",
            "otaviolb77",
            "otaviolb.ninja",
            "otavio77",
            "9 9 9 9",
            "12.345.678-9",
            "Atlantica",
        ],
        "indiretos": ["Lumen", "Vetor"],
        "tecnicos": ["FastAPI", "PostgreSQL", "Redis", "AWS", "APIs"],
    },
    {
        "nome": "Iracema Duarte",
        "atributos": {"telefone": "+55 11 97777-1234", "links": "linktr.ee/iraduarte9"},
        "texto": (
            "Sou Iracema Duarte, engenheira de dados. Tel +55 11 97777-1234. "
            "Links: linktr.ee/iraduarte9 e bit.ly/ira99. Passei 3 anos no Banco Aurora "
            "construindo pipelines em Spark e Airflow. Fui orientada pela Dra. Helena Vasques. "
            "Graduada pela UFPE. Mentorei a colega ana clara ribeiro em SQL."
        ),
        "diretos": ["Iracema", "Duarte", "97777-1234", "iraduarte9", "ira99"],
        "indiretos": ["Banco Aurora", "Helena Vasques", "UFPE", "ana clara ribeiro"],
        "tecnicos": ["Spark", "Airflow", "SQL", "pipelines"],
    },
    {
        "nome": "Ruan Cavalcante",
        "atributos": {"usuario": "ruancode42", "email": "ruan@example.invalid"},
        "texto": (
            "Ruan C. Cavalcante | ruan@example.invalid | github ruancode42 | 415-555-0147\n"
            "Developer at Northwind Labs, trabalhando com React, Next.js e Node.js. "
            "Liderou a migração para TypeScript. R. dos Coqueiros, 12, Recife. "
            "Telefone alternativo (81) 3333-2222."
        ),
        "diretos": [
            "Ruan",
            "Cavalcante",
            "ruan@",
            "ruancode42",
            "555-0147",
            "Coqueiros",
            "3333-2222",
        ],
        "indiretos": ["Northwind"],
        "tecnicos": ["React", "Next.js", "Node.js", "TypeScript"],
    },
    {
        "nome": "Marta Sá",
        "atributos": {"portfolio": "https://msa-dev.example.com"},
        "texto": (
            "Marta Sá. Portfólio: msa-dev.example.com. Twitter: @msa_dev. "
            "Trabalho no Grupo Horizonte com Java e Spring Boot, em Microsservicos. "
            "Antes, Consultoria Alfa Beta. Formação: Instituto Tecnologico Boa Vista. "
            "Cep 50000-000."
        ),
        "diretos": ["Marta", "msa-dev", "@msa_dev", "50000-000"],
        "indiretos": ["Grupo Horizonte", "Consultoria Alfa", "Instituto Tecnologico Boa Vista"],
        "tecnicos": ["Java", "Spring Boot"],
    },
    {
        "nome": "Teodoro Nunes Falcao",
        "atributos": {},
        "texto": (
            "T e o d o r o  N u n e s é meu nome completo. "
            "Тeodoro Falcao escreve APIs em Go e gRPC. "
            "Te\U000e0001odoro N︀unes publicou em conferências de Kafka. "
            "Colegas: Priscila Moraes e Joana. "
            "Certificado AWS Solutions Architect e Scrum Master."
        ),
        "diretos": ["T e o d o r o", "N u n e s", "Тeodoro", "Falcao", "Te\U000e0001odoro"],
        "indiretos": ["Priscila Moraes", "Joana"],
        "tecnicos": ["APIs", "Go", "gRPC", "Kafka", "AWS", "Scrum"],
    },
]


def _vazamentos(curriculo: dict, campo: str, texto: str) -> list[str]:
    return [termo for termo in curriculo[campo] if termo in texto]


def test_medicao_de_vazamento_em_curriculos_sinteticos():
    """Mede o conjunto todo e compara com as metas declaradas acima.

    O conjunto é pequeno e foi escrito junto com as regras: mede regressão, não taxa real. Para
    um número que valha fora daqui, é preciso um conjunto novo, que as regras nunca viram.
    """
    diretos = indiretos = tecnicos = 0
    vazou_direto: list[str] = []
    vazou_indireto: list[str] = []
    perdeu_tecnico: list[str] = []
    for indice, curriculo in enumerate(CURRICULOS_SINTETICOS):
        candidato = cand(
            curriculo["texto"],
            nome=curriculo["nome"],
            cid=f"cv{indice}",
            atributos=curriculo["atributos"],
        )
        texto = preparar_perfil(candidato, pseudonimizador=Pseudonimizador()).texto
        diretos += len(curriculo["diretos"])
        indiretos += len(curriculo["indiretos"])
        tecnicos += len(curriculo["tecnicos"])
        vazou_direto += _vazamentos(curriculo, "diretos", texto)
        vazou_indireto += _vazamentos(curriculo, "indiretos", texto)
        perdeu_tecnico += [t for t in curriculo["tecnicos"] if t not in texto]

    print(
        f"vazamento direto {len(vazou_direto)}/{diretos}; "
        f"indireto {len(vazou_indireto)}/{indiretos} {vazou_indireto}; "
        f"técnicos perdidos {len(perdeu_tecnico)}/{tecnicos} {perdeu_tecnico}"
    )
    assert len(vazou_direto) / diretos <= META_VAZAMENTO_DIRETO, vazou_direto
    assert len(vazou_indireto) / indiretos <= META_VAZAMENTO_INDIRETO, vazou_indireto
    assert 1 - len(perdeu_tecnico) / tecnicos >= META_RETENCAO_TECNICA, perdeu_tecnico


@pytest.mark.parametrize(
    "texto",
    [
        "Uso Node.js, Vue.js e Next.js com ASP.NET e Socket.IO.",
        "Editei o README.md, o arquivo main.py e o config.yaml.",
        "Chamei os.path e pandas.read_csv no pipeline.",
        "Pesquisa terminou.Depois fui para outra área.",
        "Doutor Ph.D em computação, e.g. redes.",
        "Python 3.12, versão 2.7.18 e v1.2.3.",
    ],
)
def test_arquivo_e_tecnologia_nao_viram_link(texto):
    resultado = preparar_perfil(cand(texto, atributos={}), pseudonimizador=Pseudonimizador())
    assert "[LINK" not in resultado.texto, resultado.texto


@pytest.mark.parametrize(
    "texto",
    [
        "Faço React Native e Google Cloud Platform.",
        "Fui Gerente de Produto e Engenheira de Dados.",
        "Machine Learning Engineer e Tech Lead.",
        "EXPERIÊNCIA PROFISSIONAL\nFORMAÇÃO ACADÊMICA\nHABILIDADES TÉCNICAS",
        "Meu GitHub é público e tenho GitHub Actions.",
    ],
)
def test_expressao_tecnica_nao_vira_nome(texto):
    resultado = preparar_perfil(cand(texto, atributos={}), pseudonimizador=Pseudonimizador())
    assert "[NOME" not in resultado.texto, resultado.texto
    assert "[PERFIL" not in resultado.texto, resultado.texto


@pytest.mark.parametrize(
    "disfarce",
    [
        "［EMAIL_1］",
        "[ＥＭＡＩＬ_１]",
        "﹇EMAIL_1﹈",
        "[EM​AIL_1]",
        "[EM\U000e0041AIL_1]",
        "［PESSOA］",
    ],
)
def test_L5_nenhuma_variante_de_marcador_forjado_chega_ao_prompt(disfarce):
    candidato = cand(f"Contato {disfarce} fez APIs", nome="Zulmira Prado", atributos={})
    resultado = preparar_perfil(candidato, pseudonimizador=Pseudonimizador())
    assert not MARCADOR.search(como_dado(resultado.texto)), como_dado(resultado.texto)


def test_L2_nome_do_site_conhecido_sai_mesmo_sozinho():
    candidato = cand(
        "Meu blog analima tem textos sobre Python.",
        atributos={"site": "https://analima.ninja/blog"},
    )
    resultado = preparar_perfil(candidato, pseudonimizador=Pseudonimizador())
    assert "analima" not in resultado.texto, resultado.texto


def test_identificador_cortado_pela_frase_volta_inteiro_pela_fonte():
    """O ponto de `R.` e de `gmail .` corta a frase: cada pedaço guarda o caminho até o original."""
    pseudonimizador = Pseudonimizador()
    candidato = cand("Moro na R. das Flores, 123. Fiz APIs.", nome="Zulmira Prado", atributos={})
    resultado = preparar_perfil(candidato, pseudonimizador=pseudonimizador)
    assert "Flores" not in resultado.texto
    assert resultado.pseudonimizado.na_fonte("Fiz APIs.").texto == "Fiz APIs."
    revelados = [
        pseudonimizador.cofre.revelar(EMP, "c1", marcador)
        for marcador in resultado.pseudonimizado.marcadores
    ]
    assert "das Flores, 123" in revelados


@pytest.mark.parametrize(
    "texto",
    [
        "Maria Lima " * 18000,
        "a." * 95000,
        "a@" * 95000,
        "1 " * 95000,
        "Rua " * 45000,
        "R. das " * 25000,
        "A. " * 60000,
        "CARLOS " * 25000,
    ],
    ids=["nomes", "pontos", "arrobas", "digitos", "ruas", "abreviacoes", "iniciais", "caixa_alta"],
)
def test_H4_texto_repetitivo_de_200k_nao_trava(texto):
    codigo = f"""
    from datetime import date
    from backend.contratos.modelos import Candidato
    from backend.fontes.anonimizador import Pseudonimizador
    c = Candidato(
        id='c', empresa_id='e', nome='Maria Lima', fonte='x', simulado=True, origem='p',
        atualizado_em=date(2026, 1, 1), autorizacao_valida_ate=None, estado='ativo',
        perfil_texto={texto!r}, atributos={{}}, historico=[], autorizou_contato=True,
    )
    print(len(Pseudonimizador().pseudonimizar(c).texto))
    """
    tempo, retorno, saida, erro = _rodar_com_limite(codigo, 25)
    assert tempo < 20, f"tempo={tempo} saida={saida} erro={erro}"
    assert retorno == 0, erro


def test_perfil_maior_que_o_limite_e_cortado_e_nao_vai_inteiro_ao_modelo():
    texto = "Fiz APIs em Python. " * 20_000
    assert len(texto) > MAXIMO_DE_CARACTERES_DO_PERFIL
    resultado = Pseudonimizador().pseudonimizar(cand(texto, atributos={}))
    assert len(resultado.fonte) <= MAXIMO_DE_CARACTERES_DO_PERFIL


# ---------- B-3 ----------
def test_L5_marcador_forjado_em_largura_total_nao_vira_marcador_no_prompt():
    resultado = preparar_perfil(
        cand("Contato ［EMAIL_1］ fez APIs", atributos={}), pseudonimizador=Pseudonimizador()
    )
    assert "[EMAIL_1]" not in como_dado(resultado.texto)


# ---------- A-9 ----------
def test_H4_texto_de_200k_com_o_nome_repetido_nao_trava():
    codigo = """
    from datetime import date
    from backend.contratos.modelos import Candidato
    from backend.fontes.anonimizador import Pseudonimizador
    c = Candidato(
        id='c', empresa_id='e', nome='Maria Lima', fonte='x', simulado=True, origem='p',
        atualizado_em=date(2026, 1, 1), autorizacao_valida_ate=None, estado='ativo',
        perfil_texto='Maria ' * 33000, atributos={}, historico=[], autorizou_contato=True,
    )
    print(len(Pseudonimizador().pseudonimizar(c).texto))
    """
    tempo, retorno, saida, erro = _rodar_com_limite(codigo, 25)
    assert tempo < 20, f"tempo={tempo} saida={saida} erro={erro}"
    assert retorno == 0, erro


def test_H5_conferencia_de_trecho_com_marcadores_nao_explode():
    codigo = """
    from backend.agente.neutralizacao import corresponde_ao_original
    trecho = ' x '.join(['[PESSOA]'] * 12) + ' fim'
    original = ('Ana x ' * 400) + 'Ana x ' * 11 + 'Ana FIM_NAO'
    print(corresponde_ao_original(trecho, original))
    """
    tempo, retorno, saida, erro = _rodar_com_limite(codigo, 25)
    assert tempo < 20, f"tempo={tempo} saida={saida} erro={erro}"
    assert retorno == 0, erro
