# Plano de implementação: agente recrutador conectado à Nara

> **Para agentes:** execute uma tarefa de `tasks.md` por vez, com teste antes do código. Use subagent-driven-development ou executing-plans quando disponíveis; caso contrário, use `/speckit-implement`.

**Objetivo:** construir um digital worker que constrói o banco de talentos de cada empresa, encontra candidatos nele, explica escolhas, faz o primeiro contato e entrega o contexto à Nara simulada.

**Arquitetura:** máquina de estados em código, com IA nas decisões abertas. Fontes, mensagens e Nara ficam atrás de interfaces, com simulações trocáveis. API e MCP usam o mesmo núcleo.

**Tecnologias:** Python 3.12, FastAPI, Pydantic, SQLite, pytest, ruff, Langfuse, cliente OpenAI com Featherless, Next e TypeScript.

**Spec:** `specs/001-agente-recrutador/spec.md`. **Design:** `docs/superpowers/specs/2026-11-07-agente-recrutador-design.md`.

## Restrições globais

- Código do projeto a partir de 7/11/2026, às 10h. Submissão até 8/11/2026, às 13h.
- Somente dados sintéticos. Sem scraping do LinkedIn.
- Um banco por empresa. Sem autorização válida, o perfil não entra na busca.
- O agente não agenda entrevistas nem decide contratações.
- Regras, autorização, limites de contato e cálculos são determinísticos.
- Modelo padrão: `zai-org/GLM-5.2`, com `max_tokens` de pelo menos 1000.
- Simulações são identificadas com `simulado=True` na API e na interface.
- Chaves ficam só em variáveis de ambiente.
- Toda consulta recebe `empresa_id`; nenhum dado é lido sem esse escopo.
- Chamadas externas têm tempo limite; o valor padrão é 30 segundos.

## Foco de revisão

1. **Currículo com instruções ao agente:** deve ser tratado como dado, com alerta. Testado em T2.3.
2. **Mesma pessoa em fontes ou páginas diferentes:** deve aparecer uma vez. Testado em T2.2.
3. **Opt-out no meio da conversa ou entre buscas:** não pode haver novo contato. Testado em T3.2.
4. **Falha depois de envio aceito:** repetir não pode duplicar convite nem entrega. Testado em T3.1 e T3.3.
5. **Limite de gasto atingido no meio da execução:** deve pausar com estado salvo, não falhar sem explicação. Testado em T1.3.

## Estrutura

```text
backend/
  contratos/      modelos.py, interfaces.py, erros.py, simulacoes.py  (compartilhada)
  agente/         regras.py, fluxo.py, configuracao.py, persistencia.py, auditoria.py, rotina_banco.py, aprendizado.py, api.py, mcp.py
  modelos/        cliente.py, resiliencia.py
  fontes/         banco_talentos.py, consultas.py, funil.py, documentos.py, rede_simulada.py, analisador.py, revisor.py, github_teste.py
  contato/        mensageiro.py, conversa.py, cadastro.py, recontato.py, pacote.py
  nara_simulada/  servico.py
dados/            gerador.py, sinteticos/
avaliacoes/       casos/, test_avaliacoes.py, relatorio.py
web/              app/
docs/pitch/
tests/            testes por pasta do backend
```

## Contratos

Definidos em `backend/contratos/modelos.py` (Pydantic v2):

```python
class Competencia(BaseModel): nome: str; peso: float
class Requisito(BaseModel): id: str; descricao: str; campo: str; valor_esperado: str
class Vaga(BaseModel):
    id: str; empresa_id: str; titulo: str; descricao: str
    requisitos: list[Requisito]; competencias: list[Competencia]
    meta_candidatos: int; prazo_dias: int; max_tentativas_contato: int
    aprovada: bool = False
class Experiencia(BaseModel): empresa: str; cargo: str; inicio: date; fim: date | None; descricao: str
class EstadoBanco(StrEnum): PENDENTE="pendente"; ATIVO="ativo"; DESATUALIZADO="desatualizado"; EXPIRADO="expirado"; REMOVIDO="removido"
class Candidato(BaseModel):
    id: str; empresa_id: str; nome: str; fonte: str; simulado: bool
    origem: str; atualizado_em: date; autorizacao_valida_ate: date | None; estado: EstadoBanco
    perfil_texto: str; atributos: dict[str, str]; historico: list[Experiencia]
    autorizou_contato: bool; opt_out: bool = False
class Evidencia(BaseModel): criterio: str; trecho: str; fonte: str
class Analise(BaseModel):
    vaga_id: str; candidato_id: str; requisitos_ok: dict[str, bool]; notas: dict[str, float]
    evidencias: list[Evidencia]; lacunas: list[str]; pontos_a_aprofundar: list[str]
    alertas: list[str]; ressalvas_revisor: list[str] = []
class TipoDecisao(StrEnum): DESCARTAR="descartar"; INDICAR="indicar"; PEDIR_HUMANO="pedir_humano"
class Decisao(BaseModel):
    vaga_id: str; candidato_id: str; tipo: TipoDecisao; regra: str; motivo: str; responsavel: str; rastro_id: str
    entrada: dict[str, str]; evidencias: list[Evidencia]; momento: datetime
class TipoConvite(StrEnum): AUTORIZACAO="autorizacao"; VAGA="vaga"
class Convite(BaseModel):
    id: str; empresa_id: str; tipo: TipoConvite; canal: str; vaga_id: str | None; candidato_id: str; mensagem: str; link_nara: str; chave_idempotencia: str; simulado: bool
class TipoResposta(StrEnum): ACEITE="aceite"; RECUSA="recusa"; DUVIDA="duvida"; SILENCIO="silencio"; OPT_OUT="opt_out"
class RespostaCandidato(BaseModel): convite_id: str; tipo: TipoResposta; texto: str = ""
class PacoteNara(BaseModel):
    vaga_id: str; candidato_id: str; motivo_por_criterio: dict[str, str]
    historico: list[Experiencia]; evidencias: list[Evidencia]; lacunas: list[str]
    pontos_a_aprofundar: list[str]; ressalvas_revisor: list[str]
    autorizacao: str; fonte: str; rastro_id: str; chave_idempotencia: str
class ResultadoNara(BaseModel): vaga_id: str; candidato_id: str; notas: dict[str, float]; aprovado: bool; simulado: bool = True
class PropostaAjuste(BaseModel): vaga_id: str; motivo: str; antes: Vaga; depois: Vaga; resultado_avaliacao: dict[str, float]; aprovada: bool = False
class EventoFluxo(BaseModel): vaga_id: str; etapa: str; mensagem: str; candidato_id: str | None = None; custo_usd: float = 0; momento: datetime
```

Definidos em `backend/contratos/interfaces.py` (`typing.Protocol`):

```python
class FonteCandidatos(Protocol):
    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]: ...
class BancoTalentos(FonteCandidatos, Protocol):
    def importar(self, empresa_id: str, registros: list[dict]) -> list[Candidato]: ...
    def registrar_autorizacao(self, empresa_id: str, candidato_id: str, valida_ate: date) -> Candidato: ...
    def atualizar(self, empresa_id: str, candidato_id: str, dados: dict[str, str]) -> Candidato: ...
    def remover(self, empresa_id: str, candidato_id: str) -> None: ...
    def vencendo(self, empresa_id: str, ate: date) -> list[Candidato]: ...
class Analisador(Protocol):
    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise: ...
class Revisor(Protocol):
    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise: ...
class Mensageiro(Protocol):
    def enviar(self, convite: Convite) -> bool: ...
class ClienteNara(Protocol):
    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str: ...
    def entregar(self, pacote: PacoteNara) -> bool: ...
    def resultados(self, vaga_id: str) -> list[ResultadoNara]: ...
class ClienteModelo(Protocol):
    def completar(self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str) -> BaseModel: ...
```

Erros compartilhados, em `backend/contratos/erros.py`: `FonteIndisponivel`, `ModeloIndisponivel`, `RespostaInvalida`, `LimiteGastoAtingido`.

Em `backend/contratos/simulacoes.py` ficam as simulações de todas as interfaces, usadas pelas frentes enquanto as implementações reais não chegam.

## Persistência

SQLite em arquivo local, por decisão de design, sem Postgres até haver necessidade. Tabelas: execuções, eventos, decisões, convites e chaves de idempotência. O banco de talentos pode começar no mesmo arquivo. Dados sintéticos são recarregados por `POST /sessoes/reiniciar`.

## Estados do fluxo

`RASCUNHO → AGUARDANDO_APROVACAO → BUSCANDO → ANALISANDO → REVISANDO → DECIDINDO → AGUARDANDO_LOTE → CONVIDANDO → ENTREGANDO → CONCLUIDA`

Também existem `PAUSADA` (falha recuperável ou limite de gasto) e `META_EM_RISCO`.

## Integração das frentes

1. T0 é feita em conjunto.
2. Cada frente usa simulações das interfaces até a integração das demais.
3. O ponto de encontro é `backend/agente/fluxo.py`, que recebe as interfaces por injeção. A busca usa o `BancoTalentos` antes das fontes externas.
4. No marco das 13h de sábado, o fluxo roda com implementações simples. No marco das 17h, com as reais.
