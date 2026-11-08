# Contato e Nara simulada

Guia do que a Frente 1 chama em `backend/contato` e `backend/nara_simulada`, como está na `main`. Envio, entrevista e MCP daqui são simulados. Quem libera o contato continua sendo `pode_contatar`, no fluxo.

Os exemplos usam `empresa-demo`, `pessoa-000` e `example.invalid`. `candidato_simulado` deixa a pessoa ativa, com `autorizou_contato=True`, `opt_out=False`, `simulado=True` e autorização até 2027-11-07.

```python
from backend.contratos.modelos import Analise, Competencia, Evidencia, Requisito, Vaga
from backend.contratos.simulacoes import candidato_simulado

vaga = Vaga(
    id="vaga-000",
    empresa_id="empresa-demo",
    titulo="Backend",
    descricao="Trabalho remoto.",
    requisitos=[
        Requisito(id="req-python", descricao="Python", campo="linguagem", valor_esperado="python")
    ],
    competencias=[Competencia(nome="apis", peso=1.0)],
    meta_candidatos=3,
    prazo_dias=7,
    max_tentativas_contato=2,
)
candidato = candidato_simulado(
    "pessoa-000", "empresa-demo", nome="Pessoa 000", fonte="fonte-sintetica", origem="importacao-sintetica"
)
analise = Analise(
    empresa_id="empresa-demo",
    vaga_id="vaga-000",
    candidato_id="pessoa-000",
    requisitos_ok={"req-python": True},
    notas={"apis": 0.8},
    evidencias=[Evidencia(criterio="apis", trecho="publicou uma API", fonte="fonte-sintetica")],
    lacunas=[],
    pontos_a_aprofundar=[],
    alertas=[],
)
```

## `criar_convite`

```python
def criar_convite(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    link_agendamento: str | None,
    cliente_modelo: ClienteModelo,
    *,
    preferencias: PreferenciasContato | None = None,
    tentativa: int = 1,
) -> Convite:
```

`PreferenciasContato` tem `personalizar: bool = True` e `canal: str = "simulado"`.

O fluxo pede o texto em `_texto_do_convite`, com o convite em `A_ENVIAR` e análise presente: `redator_convite(vaga, candidato, analise, link)`. A demonstração implementa esse redator com `criar_convite` e `personalizar=False`, e devolve só `convite.mensagem`. O `Convite` que o fluxo envia é o gravado em `_novo_convite`.

Devolve `Convite` com `tipo=TipoConvite.VAGA`, `canal` das preferências, `simulado=True` e chave `{empresa}:{vaga}:{candidato}:vaga:{tentativa}`. O texto é a redação do modelo ou a mensagem padrão, já com o nome e, se houver, o link no lugar de `{link_agendamento}`.

A origem do contato no texto do convite ainda está na PR #87 (`frente/contato-convite-origem`), aberta. Na `main`, a mensagem traz o título e `SAIR`, e o link quando ele existe. `fonte`, `origem` e o aviso de simulação ficam fora desse texto.

Levanta `ValueError` se vaga, candidato e análise não forem da mesma empresa, ou se a análise não for desta vaga e desta pessoa. `ModeloIndisponivel` e `RespostaInvalida` não sobem: a função usa a mensagem padrão.

Modelo: sim, na etapa `redigir_convite`, só com `personalizar=True`. Com `personalizar=False` não há chamada.

```python
from backend.contato.mensageiro import PreferenciasContato, criar_convite
from backend.contratos.simulacoes import ClienteModeloSimulado

convite = criar_convite(
    vaga,
    candidato,
    analise,
    "https://nara.simulada.local/agendar/vaga-000/pessoa-000",
    ClienteModeloSimulado(),
    preferencias=PreferenciasContato(personalizar=False),
)
```

## `MensageiroSimulado`

```python
class MensageiroSimulado:
    def __init__(self, falhas_restantes: int = 0, falhas_apos_envio: int = 0) -> None: ...
    def enviar(self, convite: Convite) -> bool: ...
    def enviados(self, empresa_id: str) -> list[Convite]: ...
```

O fluxo chama `mensageiro.enviar(convite)` em `_enviar`, depois de conferir `pode_contatar` de novo. A demonstração injeta `MensageiroSimulado()`.

`enviar` devolve `True` quando gravou ou quando a `chave_idempotencia` já estava na caixa da empresa. Devolve `False` se `falhas_restantes` consome uma falha antes de gravar, ou se `falhas_apos_envio` grava e mesmo assim devolve falha. Repetir a mesma chave não duplica.

Levanta `ValueError` com convite `simulado=False` (`não há canal real: o mensageiro só envia convites simulados`) e com `empresa_id` vazio em `enviar` ou `enviados`.

Modelo: não.

```python
from backend.contato.mensageiro import MensageiroSimulado

caixa = MensageiroSimulado()
saiu = caixa.enviar(convite)
caixa.enviados("empresa-demo")
```

## `criar_email`

```python
def criar_email(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    contato: ContatoPublicado,
    remetente: Remetente,
    lista: ListaSupressao,
    cliente_modelo: ClienteModelo,
    *,
    personalizar: bool = True,
    tentativa: int = 1,
) -> EmailConvite:
```

`ContatoPublicado` pede `canal`, `endereco`, `url_origem`, `descricao_origem`, `coletado_em` e `publicado_para_contato`. `Remetente` pede `nome_empresa` e `numero_whatsapp` só com dígitos.

A Frente 1 chama na hora de montar o e-mail da vaga. `tentativa=1` é o e-mail inicial. `tentativa=2` é o lembrete único. O fluxo da `main` ainda não importa esta função; `pode_contatar` segue no fluxo.

Devolve `EmailConvite`: `convite` (`canal="email"`, `simulado=True`, `link_agendamento=None`), `para`, `assunto`, `cabecalhos`, `codigo`, `link_whatsapp` e `link_exclusao`. O corpo junta a abertura, o WhatsApp com o código, a origem publicada, o link de exclusão, `SAIR` e a frase de simulação. O modelo escreve só a abertura, na tentativa 1.

Levanta `ContatoBloqueado` antes de chamar o modelo. Levanta `ValueError` se `tentativa` não for 1 ou 2, ou se vaga, candidato e análise não baterem. Falha de modelo não sobe: a abertura volta ao parágrafo padrão. Na tentativa 2 a abertura é fixa.

Modelo: sim, na etapa `redigir_email`, só com `personalizar=True` e `tentativa=1`. O lembrete não chama modelo.

```python
from datetime import UTC, datetime

from backend.contato.email_inicial import ContatoPublicado, Remetente, criar_email
from backend.contato.supressao import ListaSupressao
from backend.contratos.simulacoes import ClienteModeloSimulado

lista = ListaSupressao(b"exemplo")
contato = ContatoPublicado(
    canal="email",
    endereco="pessoa-000@example.invalid",
    url_origem="https://example.invalid/pessoa-000",
    descricao_origem="perfil público sintético",
    coletado_em=datetime(2026, 11, 8, 12, tzinfo=UTC),
    publicado_para_contato=True,
)
email = criar_email(
    vaga,
    candidato,
    analise,
    contato,
    Remetente(nome_empresa="Empresa Demo", numero_whatsapp="5500000000000"),
    lista,
    ClienteModeloSimulado(),
    personalizar=False,
)
```

## `ContatoBloqueado`

```python
class ContatoBloqueado(Exception):
    def __init__(self, regra: str) -> None: ...
```

O atributo `regra` repete a mensagem. `criar_email` levanta com `canal_nao_e_email`, `contato_nao_publicado` (contato não publicado ou `url_origem` vazia) ou `lista_supressao`.

`MensageiroEmailSimulado.enviar(email) -> bool` consulta a lista de novo e levanta `ContatoBloqueado("lista_supressao")` se a pessoa saiu depois da montagem. Também levanta `ValueError` para e-mail com `simulado=False` ou `empresa_id` vazio. `False` é falha injetada; `True` é enviado ou chave repetida.

Modelo: não.

```python
from backend.contato.email_inicial import ContatoBloqueado

try:
    criar_email(
        vaga, candidato, analise,
        contato.model_copy(update={"publicado_para_contato": False}),
        Remetente(nome_empresa="Empresa Demo", numero_whatsapp="5500000000000"),
        lista, ClienteModeloSimulado(), personalizar=False,
    )
except ContatoBloqueado as erro:
    erro.regra  # "contato_nao_publicado"
```

## `responder_duvida`

```python
def responder_duvida(vaga: Vaga, texto: str, cliente_modelo: ClienteModelo) -> str | None:
```

O fluxo chama o `respondedor_duvida(vaga, candidato, texto)` em `_tratar_duvida`, quando a resposta classificada é dúvida. Esta função recebe a vaga, o texto e o cliente de modelo. A demonstração usa `responder_duvida_demo`, sem esta função.

Devolve o texto da resposta, ou `None`. `None` significa encaminhar a uma pessoa. Isso vale para texto vazio, texto com instrução ao agente, modelo indisponível ou resposta inválida, e resposta que não se apoia em trechos literais do material da vaga.

`ModeloIndisponivel` e `RespostaInvalida` não sobem. Texto vazio ou com instrução devolve `None` sem chamar o modelo.

Modelo: sim, na etapa `responder_duvida`, nos demais casos.

```python
from backend.contato.conversa import responder_duvida
from backend.contratos.simulacoes import ClienteModeloSimulado

modelo = ClienteModeloSimulado(
    {
        "responder_duvida": {
            "respondivel": True,
            "resposta": "A vaga é em trabalho remoto.",
            "trechos_usados": ["Trabalho remoto."],
        }
    }
)
resposta = responder_duvida(vaga, "A vaga é remota?", modelo)
```

## `mensagem_pos_entrevista`

```python
def mensagem_pos_entrevista(vaga: Vaga, resultado: ResultadoEntrevista) -> str:
```

A Frente 1 chama depois da entrevista, para comunicar o `ResultadoEntrevista` que a Nara simulada devolveu. A função só comunica: aprovado segue no processo; reprovado encerra a candidatura. O fluxo da `main` ainda não importa esta função.

Devolve uma string. O nome continua no marcador `{nome}`. O texto cita o título, o próximo passo, `SAIR` e, com `resultado.simulado` (padrão `True`), o aviso de simulação. Nota e ranking ficam de fora.

Levanta `ValueError` se `resultado.empresa_id` ou `resultado.vaga_id` não forem os da vaga.

Modelo: não.

```python
from backend.contato.pos_entrevista import mensagem_pos_entrevista
from backend.contratos.modelos import ResultadoEntrevista

texto = mensagem_pos_entrevista(
    vaga,
    ResultadoEntrevista(
        empresa_id="empresa-demo",
        vaga_id="vaga-000",
        candidato_id="pessoa-000",
        notas={"apis": 0.8},
        aprovado=True,
    ),
)
```

## `decidir_lembrete`

```python
def decidir_lembrete(
    situacao: SituacaoContato, hoje: datetime, intervalo: timedelta = INTERVALO_PADRAO
) -> DecisaoLembrete:
```

`INTERVALO_PADRAO` é 3 dias. `SituacaoContato` leva `empresa_id`, `vaga_id`, `candidato_id`, `para`, `enviado_em` e, opcionais, `lembrete_em`, `respondeu_em`, `suprimido` e `encerrado`.

A Frente 1 chama para decidir o único lembrete de quem não respondeu. O fluxo da `main` ainda não importa esta função. A rodada que envia é `AgendaLembretes.processar(hoje, criar_lembrete, emails, *, intervalo=INTERVALO_PADRAO, pode_contatar=None) -> list[DecisaoLembrete]`. Ela chama `decidir_lembrete`. `pode_contatar`, quando informado, recebe `(empresa_id, vaga_id, candidato_id)`.

Devolve `DecisaoLembrete` com `empresa_id`, `vaga_id`, `candidato_id`, `acao`, `regra` e `momento`. A ação é `esperar`, `enviar_lembrete`, `encerrar_silencio` ou `nada`. A regra é `dentro_do_intervalo`, `intervalo_sem_resposta`, `silencio_apos_lembrete`, `respondeu`, `lista_supressao` ou `encerrado`. Há no máximo um lembrete; depois dele, o silêncio encerra.

`decidir_lembrete` não levanta exceção própria. `hoje` precisa ser comparável com `enviado_em`. `processar` devolve os lembretes enviados, os bloqueios e os encerramentos por silêncio. `esperar` e quem já estava em `nada` ficam fora dessa lista. `ContatoBloqueado` no envio vira decisão `nada` com a `regra` do erro e não sobe. Bloqueio de `pode_contatar` usa a regra `pode_contatar`. `registrar_envio` levanta `ValueError` se o e-mail não for a tentativa 1.

Modelo: não, nem na decisão nem na agenda. O texto do lembrete sai de `criar_email(..., tentativa=2)`.

```python
from datetime import UTC, datetime

from backend.contato.lembrete import SituacaoContato, decidir_lembrete

decisao = decidir_lembrete(
    SituacaoContato(
        empresa_id="empresa-demo",
        vaga_id="vaga-000",
        candidato_id="pessoa-000",
        para="pessoa-000@example.invalid",
        enviado_em=datetime(2026, 11, 1, 12, tzinfo=UTC),
    ),
    datetime(2026, 11, 5, 12, tzinfo=UTC),
)
```

## `ListaSupressao`

```python
class ListaSupressao:
    def __init__(self, segredo: bytes) -> None: ...
    def suprimir(self, empresa_id: str, identidades: list[str]) -> None: ...
    def esta_suprimido(self, empresa_id: str, identidades: list[str]) -> bool: ...
    def hashes(self, empresa_id: str) -> list[str]: ...
    def link_exclusao(self, empresa_id: str, candidato_id: str, identidades: list[str]) -> str: ...
    def aplicar_exclusao(self, token: str) -> PedidoExclusao | None: ...
    @staticmethod
    def cabecalhos_exclusao(link: str) -> dict[str, str]: ...
```

A Frente 1 consulta `esta_suprimido` antes de cada contato e chama `aplicar_exclusao` no clique do link. A lista é por empresa e vale para todas as vagas. O segredo vem da configuração e não entra no repositório nem em log. A lista guarda HMAC, não o e-mail.

`suprimir` é idempotente. `esta_suprimido` é verdadeiro se qualquer identidade da lista estiver bloqueada. `hashes` devolve os HMAC da empresa, ordenados. `link_exclusao` devolve `https://contato.simulado.local/sair/{token}`, sempre o mesmo para a mesma pessoa, sem dado pessoal na URL. `aplicar_exclusao` devolve `PedidoExclusao` (`empresa_id`, `candidato_id`, `aplicado_em`) ou `None` se o token não existe. O segundo clique devolve o mesmo pedido. `cabecalhos_exclusao` devolve `List-Unsubscribe` e `List-Unsubscribe-Post`.

Levanta `ValueError` se `segredo` for vazio, e em `link_exclusao` se não houver identidade normalizável.

Modelo: não.

```python
from backend.contato.supressao import ListaSupressao

lista = ListaSupressao(b"exemplo")
link = lista.link_exclusao("empresa-demo", "pessoa-000", ["pessoa-000@example.invalid"])
pedido = lista.aplicar_exclusao(link.rsplit("/", 1)[-1])
lista.esta_suprimido("empresa-demo", ["pessoa-000@example.invalid"])
```

## `pode_recontatar`

```python
def pode_recontatar(
    candidato: Candidato,
    historico: list[RegistroContato],
    hoje: date,
    **opcoes,
) -> bool:
```

Os argumentos nomeados vão para `bloqueio_recontato`: `lista`, `identidades` e `intervalo` (`INTERVALO_RECONTATO`, 90 dias). `RegistroContato` tem `empresa_id`, `candidato_id`, `momento` e `resposta` opcional.

A Frente 1 chama quando uma vaga nova olha o banco antes do hunting. O fluxo da `main` ainda não importa esta função. `False` registra a regra no log. `bloqueio_recontato` devolve a regra, ou `None` se pode: `saiu`, `estado`, `sem_autorizacao`, `lista_supressao`, `recusou` ou `intervalo`. Silêncio e aceite não bloqueiam. Contato de outra empresa não entra na conta.

Não levanta exceção. Argumento nomeado fora desses três sobe `TypeError` dentro de `bloqueio_recontato`.

Modelo: não.

```python
from datetime import date

from backend.contato.recontato import pode_recontatar
from backend.contato.supressao import ListaSupressao

lista_banco = ListaSupressao(b"exemplo")
pode = pode_recontatar(
    candidato,
    [],
    date(2026, 11, 8),
    lista=lista_banco,
    identidades=["pessoa-000@example.invalid"],
)
```

## `montar_recontato`

```python
def montar_recontato(
    candidato: Candidato,
    motivo: str,
    cliente_modelo: ClienteModelo,
    *,
    nome_empresa: str,
    link_exclusao: str,
    hoje: date,
    vaga: Vaga | None = None,
    personalizar: bool = True,
    canal: str = "email",
) -> Convite:
```

A Frente 1 chama depois de `pode_recontatar` com o histórico e a lista. Esta função confere de novo só opt-out, estado do banco e autorização, com histórico vazio e sem lista. Intervalo, recusa e supressão ficam na chamada anterior. `motivo` vem do código.

Devolve `Convite` com `simulado=True` e `link_agendamento=None`. Com `vaga`, `tipo` é `vaga`. Sem vaga, `tipo` é `autorizacao` e a chave usa `recontato-{hoje}`. A mensagem leva a abertura, a validade da autorização, o link de exclusão, `SAIR` e o aviso de simulação.

Levanta `ValueError` com `recontato não permitido: {regra}` ou se a vaga for de outra empresa. Falha de modelo não sobe: a abertura volta ao texto padrão.

Modelo: sim, na etapa `redigir_recontato`, só com `personalizar=True`.

```python
from datetime import date

from backend.contato.recontato import montar_recontato
from backend.contratos.simulacoes import ClienteModeloSimulado

convite = montar_recontato(
    candidato,
    "abriu a vaga sintética de backend",
    ClienteModeloSimulado(),
    nome_empresa="Empresa Demo",
    link_exclusao=lista_banco.link_exclusao(
        "empresa-demo", "pessoa-000", ["pessoa-000@example.invalid"]
    ),
    hoje=date(2026, 11, 8),
    vaga=vaga,
    personalizar=False,
)
```

## `montar_pacote`

```python
def montar_pacote(
    vaga: Vaga, candidato: Candidato, analise: Analise, decisao: Decisao
) -> PacoteContexto:
```

A Frente 1 chama para montar o pacote de quem foi indicado e autorizou contato, antes de `destino.entregar`. O fluxo da `main` monta o `PacoteContexto` em `_pacote` e ainda não chama esta função.

Devolve `PacoteContexto` com motivos, histórico, evidências que têm trecho, lacunas, pontos a aprofundar, ressalvas, autorização, fonte, `rastro_id` da decisão, chave `{empresa}:{vaga}:{candidato}:entrega` e `simulado` do candidato. Critério sensível e evidência sem trecho ficam de fora.

Levanta `ValueError` se os registros não forem da mesma empresa, vaga e pessoa, se a decisão não for `indicar`, ou se faltar autorização válida (`autorizou_contato`, sem opt-out, com `autorizacao_valida_ate`).

Modelo: não.

```python
from datetime import UTC, datetime

from backend.contato.pacote import montar_pacote
from backend.contratos.modelos import Decisao, TipoDecisao

pacote = montar_pacote(
    vaga,
    candidato,
    analise,
    Decisao(
        empresa_id="empresa-demo",
        vaga_id="vaga-000",
        candidato_id="pessoa-000",
        tipo=TipoDecisao.INDICAR,
        regra="indicar_com_evidencia",
        motivo="atende o requisito",
        responsavel="agente",
        rastro_id="rastro-000",
        entrada={},
        evidencias=analise.evidencias,
        momento=datetime(2026, 11, 8, 12, tzinfo=UTC),
    ),
)
```

## `NaraSimulada`

```python
class NaraSimulada:
    def __init__(self, semente: int = 0, falhas_restantes: int = 0) -> None: ...
    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str: ...
    def entregar(self, pacote: PacoteContexto) -> bool: ...
    def entregues(self, empresa_id: str) -> list[PacoteContexto]: ...
    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoEntrevista]: ...
```

Tudo isto é simulado. O fluxo usa o destino em `_link_de_agendamento` e em `_entregar`. A demonstração injeta `NaraSimulada()`.

`link_agendamento` devolve `https://nara.simulada.local/agendar/{vaga_id}/{candidato_id}`. `entregar` devolve `True` ao gravar ou ao repetir a chave, e `False` enquanto `falhas_restantes` simula a Nara fora do ar. `resultados` devolve um `ResultadoEntrevista` por pacote da vaga, com uma nota por critério de `motivo_por_criterio` (ou `geral`), reproduzível pela `semente`, `aprovado` se a média for pelo menos 0,5, e `simulado=True`.

Levanta `ValueError` se `empresa_id` for vazio em `entregar`, `entregues` ou `resultados`, e se `entregar` receber pacote com `simulado=False`.

Modelo: não.

```python
from backend.nara_simulada.servico import NaraSimulada

nara = NaraSimulada(semente=0)
nara.link_agendamento("vaga-000", "pessoa-000")
nara.entregar(pacote)
nara.resultados("empresa-demo", "vaga-000")
```

## Servidor MCP

```python
def criar_servidor(nara: NaraSimulada) -> MCPServer: ...
def configuracao_destino(empresa_id: str, url: str) -> dict[str, Any]: ...
```

Tudo isto é simulado. O servidor se chama `nara-simulada`. Para subir: `uv run python -m backend.nara_simulada.mcp --porta 8765`. O processo escuta em `http://127.0.0.1:8765/mcp`.

`criar_servidor` registra três ferramentas, ligadas à instância dada:

| Ferramenta | Argumentos | Devolve |
| --- | --- | --- |
| `nara_link_agendamento` | `empresa_id`, `vaga_id`, `candidato_id` | `link`, `simulado: true` |
| `nara_entregar_pacote` | `pacote`, `chave_idempotencia` | `entregue`, `chave_idempotencia`, `simulado: true` |
| `nara_resultados` | `empresa_id`, `vaga_id` | `resultados`, `simulado: true` |

As três levantam `ValueError` com `empresa_id` vazio. `nara_entregar_pacote` também levanta `ValueError` se o pacote não validar (`pacote fora do formato`), se a chave não for a do pacote, ou se `simulado` for falso. A mensagem não repete o conteúdo recebido.

`configuracao_destino` devolve `nome="nara"`, `empresa_id`, `url`, as três ferramentas e `simulado=True`. Esses campos preenchem o `DestinoMCP` da Frente 1. A função não levanta exceção.

Modelo: não.

```python
from backend.nara_simulada.mcp import configuracao_destino, criar_servidor
from backend.nara_simulada.servico import NaraSimulada

criar_servidor(NaraSimulada(semente=0))
configuracao_destino("empresa-demo", "http://127.0.0.1:8765/mcp")
```

## Resumo

| Símbolo | Chama modelo? | Exceção principal |
| --- | --- | --- |
| `criar_convite` | sim, `redigir_convite`, se `personalizar` | `ValueError` |
| `MensageiroSimulado.enviar` | não | `ValueError` |
| `criar_email` | sim, `redigir_email`, na tentativa 1 com `personalizar` | `ContatoBloqueado` |
| `ContatoBloqueado` | não | é a exceção |
| `responder_duvida` | sim, `responder_duvida` | nenhuma; `None` encaminha a uma pessoa |
| `mensagem_pos_entrevista` | não | `ValueError` |
| `decidir_lembrete` | não | nenhuma |
| `AgendaLembretes.processar` | não | nenhuma; `ContatoBloqueado` vira decisão |
| `ListaSupressao` | não | `ValueError` |
| `pode_recontatar` | não | nenhuma |
| `montar_recontato` | sim, `redigir_recontato`, se `personalizar` | `ValueError` |
| `montar_pacote` | não | `ValueError` |
| `NaraSimulada` | não | `ValueError` |
| ferramentas de `criar_servidor` | não | `ValueError` |
| `configuracao_destino` | não | nenhuma |
