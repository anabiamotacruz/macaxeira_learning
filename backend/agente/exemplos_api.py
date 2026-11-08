"""Exemplos sintéticos da documentação da API, e as métricas fixas até a medição chegar.

Nada aqui vem do fluxo nem de pessoas reais, e os números são ilustrativos: não medem o
agente e não devem ser citados como resultado. As rotas só servem daqui o que traz
`exemplo_fixo: true`.
"""

from datetime import UTC, datetime

from backend.contratos.modelos import (
    Candidato,
    Competencia,
    Convite,
    Decisao,
    DestinoPessoa,
    EstadoBanco,
    EventoFluxo,
    Evidencia,
    Experiencia,
    Mandato,
    PacoteContexto,
    Politica,
    Requisito,
    ResumoExecucao,
    SaidaPersonalizada,
    TaxaMedida,
    TipoConvite,
    TipoDecisao,
    TipoErro,
    Vaga,
)

EMPRESA_EXEMPLO = "empresa-exemplo"
VAGA_EXEMPLO = "vaga-exemplo-1"
MANDATO_EXEMPLO = "mandato-exemplo-1"
MOMENTO = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
PESSOA_RESPONSAVEL = "Pessoa Responsável Fictícia"
RESPONSAVEL_AGENTE = f"agente:mandato:{MANDATO_EXEMPLO}:v1:assinante:{PESSOA_RESPONSAVEL}"
RESPONSAVEL_HUMANO = f"humano:{PESSOA_RESPONSAVEL}"
FONTE = "banco_de_talentos_simulado"
DESTINO_EXEMPLO = DestinoPessoa.TALENT_GARDEN

VAGA_NOVA = Vaga(
    id=VAGA_EXEMPLO,
    empresa_id=EMPRESA_EXEMPLO,
    titulo="Pessoa Desenvolvedora Python (vaga fictícia)",
    descricao="Vaga sintética para demonstrar o contrato da API.",
    requisitos=[
        Requisito(
            id="python",
            descricao="Experiência com Python",
            campo="linguagem",
            valor_esperado="python",
        )
    ],
    competencias=[Competencia(nome="APIs", peso=1.0)],
    meta_candidatos=2,
    prazo_dias=14,
    max_tentativas_contato=2,
)
VAGA_COM_MANDATO = VAGA_NOVA.model_copy(update={"aprovada": True})

MANDATO = Mandato(
    id=MANDATO_EXEMPLO,
    versao=1,
    empresa_id=EMPRESA_EXEMPLO,
    vaga_id=VAGA_EXEMPLO,
    hash_vaga="hash-de-exemplo",
    assinante=PESSOA_RESPONSAVEL,
    limite_gasto_usd=5.0,
    politica=Politica(limiar_verde=0.8, piso_nota=0.5, max_indicacoes=2, max_ampliacoes=1),
    assinado_em=MOMENTO,
    valido_ate=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
)


def _candidato(numero: str, nome: str, perfil: str, linguagem: str) -> Candidato:
    return Candidato(
        id=f"candidato-exemplo-{numero}",
        empresa_id=EMPRESA_EXEMPLO,
        nome=f"Pessoa Fictícia {nome}",
        fonte=FONTE,
        simulado=True,
        origem="dados_sinteticos_de_exemplo",
        atualizado_em=MOMENTO.date(),
        autorizacao_valida_ate=datetime(2027, 11, 7, tzinfo=UTC).date(),
        estado=EstadoBanco.ATIVO,
        perfil_texto=perfil,
        atributos={"linguagem": linguagem},
        historico=[],
        autorizou_contato=True,
    )


CANDIDATOS = (
    _candidato("1", "Um", "Perfil fictício: cinco anos de Python em APIs.", "python"),
    _candidato("2", "Dois", "Perfil fictício: Python declarado, sem projeto citado.", "python"),
    _candidato("3", "Três", "Perfil fictício: oito anos de Java em sistemas internos.", "java"),
)


def _decisao(
    candidato: Candidato, tipo: TipoDecisao, regra: str, motivo: str, responsavel: str, trecho: str
) -> Decisao:
    return Decisao(
        empresa_id=EMPRESA_EXEMPLO,
        vaga_id=VAGA_EXEMPLO,
        candidato_id=candidato.id,
        tipo=tipo,
        regra=regra,
        motivo=motivo,
        responsavel=responsavel,
        rastro_id=f"execucao-exemplo:{VAGA_EXEMPLO}:{candidato.id}",
        entrada={"requisito": "python"},
        evidencias=[Evidencia(criterio="python", trecho=trecho, fonte=FONTE)],
        momento=MOMENTO,
    )


DECISOES = {
    decisao.candidato_id: decisao
    for decisao in (
        _decisao(
            CANDIDATOS[0],
            TipoDecisao.INDICAR,
            "faixa_verde_v1",
            "Requisito atendido com trecho da fonte, dentro do mandato.",
            RESPONSAVEL_AGENTE,
            "cinco anos de Python",
        ),
        _decisao(
            CANDIDATOS[1],
            TipoDecisao.PEDIR_HUMANO,
            "fora_da_faixa_verde",
            "Requisito só declarado: precisa de uma pessoa antes de seguir.",
            RESPONSAVEL_AGENTE,
            "Python declarado",
        ),
        _decisao(
            CANDIDATOS[2],
            TipoDecisao.DESCARTAR,
            "funil:requisito_nao_atendido",
            "requisitos não atendidos: python",
            RESPONSAVEL_AGENTE,
            "oito anos de Java",
        ),
    )
}

DECISAO_REVERTIDA = Decisao(
    empresa_id=EMPRESA_EXEMPLO,
    vaga_id=VAGA_EXEMPLO,
    candidato_id=CANDIDATOS[0].id,
    tipo=TipoDecisao.PEDIR_HUMANO,
    regra="reversao_humana",
    motivo="Decisão revertida por uma pessoa; a original continua registrada.",
    responsavel=RESPONSAVEL_HUMANO,
    rastro_id=DECISOES[CANDIDATOS[0].id].rastro_id,
    entrada={
        "tipo_anterior": DECISOES[CANDIDATOS[0].id].tipo,
        "regra_anterior": DECISOES[CANDIDATOS[0].id].regra,
        "responsavel_anterior": DECISOES[CANDIDATOS[0].id].responsavel,
        "rastro_revertido": DECISOES[CANDIDATOS[0].id].rastro_id,
    },
    evidencias=DECISOES[CANDIDATOS[0].id].evidencias,
    momento=MOMENTO,
)

EVENTOS = (
    EventoFluxo(
        empresa_id=EMPRESA_EXEMPLO,
        vaga_id=VAGA_EXEMPLO,
        etapa="buscando",
        mensagem="aguardando_mandato -> buscando",
        momento=MOMENTO,
    ),
    EventoFluxo(
        empresa_id=EMPRESA_EXEMPLO,
        vaga_id=VAGA_EXEMPLO,
        etapa="analisando",
        mensagem="buscando -> analisando",
        candidato_id=CANDIDATOS[0].id,
        custo_usd=0.14,
        momento=MOMENTO,
    ),
    EventoFluxo(
        empresa_id=EMPRESA_EXEMPLO,
        vaga_id=VAGA_EXEMPLO,
        etapa="decidindo",
        mensagem="revisando -> decidindo",
        candidato_id=CANDIDATOS[0].id,
        custo_usd=0.28,
        momento=MOMENTO,
    ),
)

SAIDA = SaidaPersonalizada(
    empresa_id=EMPRESA_EXEMPLO,
    vaga_id=VAGA_EXEMPLO,
    pacotes=[
        PacoteContexto(
            empresa_id=EMPRESA_EXEMPLO,
            vaga_id=VAGA_EXEMPLO,
            candidato_id=CANDIDATOS[0].id,
            motivo_por_criterio={"python": "Trecho da fonte cita cinco anos de Python."},
            historico=[
                Experiencia(
                    empresa="Empresa Fictícia",
                    cargo="Pessoa Desenvolvedora",
                    inicio=datetime(2021, 11, 1, tzinfo=UTC).date(),
                    fim=None,
                    descricao="Experiência sintética.",
                )
            ],
            evidencias=DECISOES[CANDIDATOS[0].id].evidencias,
            lacunas=["Sem dado sobre testes automatizados."],
            pontos_a_aprofundar=["Tamanho dos sistemas em que atuou."],
            ressalvas_revisor=[],
            autorizacao="valida_ate:2027-11-07",
            fonte=FONTE,
            rastro_id=DECISOES[CANDIDATOS[0].id].rastro_id,
            chave_idempotencia=f"entrega:{EMPRESA_EXEMPLO}:{VAGA_EXEMPLO}:{CANDIDATOS[0].id}",
            simulado=True,
        )
    ],
    simulado=True,
    momento=MOMENTO,
)

RESUMO = ResumoExecucao(
    empresa_id=EMPRESA_EXEMPLO,
    vaga_id=VAGA_EXEMPLO,
    estado="decidindo",
    analisados=3,
    indicados=1,
    descartados=1,
    na_fila_humana=1,
    revertidos=0,
    gasto_usd=0.42,
    limite_gasto_usd=MANDATO.limite_gasto_usd,
    simulado=True,
    momento=MOMENTO,
)

NAO_MEDIDA = TaxaMedida(valor=None, casos=0, wilson_inferior=None, wilson_superior=None)
ZERO_EM_DEZ = TaxaMedida(valor=0.0, casos=10, wilson_inferior=0.0, wilson_superior=0.2775)

TAXA_SEM_REVISAO = TaxaMedida(valor=0.8, casos=20, wilson_inferior=0.584, wilson_superior=0.9193)
ERROS_POR_TIPO = {
    TipoErro.INDICACAO_ERRADA: TaxaMedida(
        valor=0.1, casos=10, wilson_inferior=0.0179, wilson_superior=0.4042
    ),
    TipoErro.DESCARTE_ERRADO: NAO_MEDIDA,
    TipoErro.VIOLACAO_ELIMINATORIA: ZERO_EM_DEZ,
    TipoErro.CONTATO_OPT_OUT: ZERO_EM_DEZ,
    TipoErro.MUDANCA_NOME_GENERO: NAO_MEDIDA,
    TipoErro.AFIRMACAO_SEM_EVIDENCIA: ZERO_EM_DEZ,
}

PEDIDO_VAGA = {
    "titulo": VAGA_NOVA.titulo,
    "descricao": VAGA_NOVA.descricao,
    "requisitos": [requisito.model_dump() for requisito in VAGA_NOVA.requisitos],
    "competencias": [competencia.model_dump() for competencia in VAGA_NOVA.competencias],
    "meta_candidatos": VAGA_NOVA.meta_candidatos,
    "prazo_dias": VAGA_NOVA.prazo_dias,
    "max_tentativas_contato": VAGA_NOVA.max_tentativas_contato,
}
PEDIDO_MANDATO = {
    "assinante": PESSOA_RESPONSAVEL,
    "limite_gasto_usd": MANDATO.limite_gasto_usd,
    "politica": MANDATO.politica.model_dump(mode="json"),
    "valido_ate": "2026-11-21T12:00:00Z",
}
PEDIDO_PARAR = {
    "responsavel": PESSOA_RESPONSAVEL,
    "motivo": "Pausa pedida pelo RH (exemplo).",
    "chave_idempotencia": "exemplo-parar-1",
}
PEDIDO_RETOMAR = {
    "responsavel": PESSOA_RESPONSAVEL,
    "motivo": "Motivo da pausa resolvido (exemplo).",
    "chave_idempotencia": "exemplo-retomar-1",
}
PEDIDO_REVERSAO = {
    "vaga_id": VAGA_EXEMPLO,
    "motivo": "Revisão humana discordou da decisão (exemplo).",
    "responsavel": PESSOA_RESPONSAVEL,
    "chave_idempotencia": "exemplo-reverter-1",
}
PEDIDO_DESTINO = {
    "vaga_id": VAGA_EXEMPLO,
    "destino": DESTINO_EXEMPLO.value,
    "responsavel": PESSOA_RESPONSAVEL,
    "chave_idempotencia": "exemplo-destino-1",
}

CONVITE = Convite(
    id=f"convite:{VAGA_EXEMPLO}:{CANDIDATOS[0].id}:1",
    empresa_id=EMPRESA_EXEMPLO,
    tipo=TipoConvite.VAGA,
    canal="simulado",
    vaga_id=VAGA_EXEMPLO,
    candidato_id=CANDIDATOS[0].id,
    mensagem="[SIMULAÇÃO] Convite fictício para a vaga de exemplo.",
    chave_idempotencia=f"convite:{EMPRESA_EXEMPLO}:{VAGA_EXEMPLO}:{CANDIDATOS[0].id}:1",
    simulado=True,
)
PEDIDO_RETORNOS = {"chave_idempotencia": "exemplo-retornos-1"}
PEDIDO_RESPOSTA = {
    "vaga_id": VAGA_EXEMPLO,
    "tipo": "aceite",
    "texto": "",
    "chave_idempotencia": "exemplo-resposta-1",
}
