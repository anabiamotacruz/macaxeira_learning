"""Rotina do banco de talentos (T1.7): manter o banco vivo sem contato demais.

`selecionar_para_contato` escolhe quem tem o perfil mais antigo, só entre quem pode receber
contato, até o limite da rodada: quem pediu para sair ou foi removido não entra.
`processar_vencidos` registra a saída de quem teve a autorização vencida. A busca do banco já
ignora essas pessoas; a decisão fica gravada para a auditoria explicar por que saíram.

Tudo aqui é regra determinística, sem modelo. A decisão não pertence a uma vaga nem a um mandato:
fica numa vaga fixa, `VAGA_DO_BANCO`, com o responsável `regra:rotina_banco`.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from backend.agente.persistencia import Repositorio
from backend.contratos.interfaces import BancoTalentos
from backend.contratos.modelos import Candidato, Decisao, EstadoBanco, TipoDecisao

VAGA_DO_BANCO = "banco-de-talentos"
RESPONSAVEL = "regra:rotina_banco"
REGRA_VENCIDA = "autorizacao_vencida"
PRAZO_ATUALIZACAO_DIAS = 180
"""Perfil sem atualização há mais tempo que isso é desatualizado e entra na rodada de contato."""
LIMITE_PADRAO = 20
MAX_PAGINAS = 500
"""Teto de páginas lidas do banco por rodada, para uma falha na paginação não virar laço."""


class RotinaBanco:
    """Seleção para atualização e saída por autorização vencida, sempre dentro da empresa."""

    def __init__(
        self,
        banco: BancoTalentos,
        repositorio: Repositorio,
        *,
        limite: int = LIMITE_PADRAO,
        prazo_atualizacao_dias: int = PRAZO_ATUALIZACAO_DIAS,
    ) -> None:
        if limite < 1:
            raise ValueError("o limite de contatos da rodada precisa ser de pelo menos 1")
        if prazo_atualizacao_dias < 1:
            raise ValueError("o prazo de atualização precisa ser de pelo menos 1 dia")
        self._banco = banco
        self._repositorio = repositorio
        self._limite = limite
        self._prazo = timedelta(days=prazo_atualizacao_dias)

    def selecionar_para_contato(self, empresa_id: str, hoje: date) -> list[Candidato]:
        """Quem pedir para atualizar o perfil: o mais antigo primeiro, até o limite."""
        _exigir_empresa(empresa_id)
        candidatos = [c for c in self._aptos(empresa_id) if self._pode_contatar(c, hoje)]
        desatualizados = [c for c in candidatos if self._desatualizado(c, hoje)]
        desatualizados.sort(key=lambda c: (c.atualizado_em, c.id))
        return desatualizados[: self._limite]

    def processar_vencidos(self, empresa_id: str, hoje: date) -> list[Decisao]:
        """Registra a saída de cada autorização vencida antes de `hoje`, uma vez por validade."""
        _exigir_empresa(empresa_id)
        ja_registradas = {
            (d.candidato_id, d.entrada.get("autorizacao_valida_ate"))
            for d in self._repositorio.listar_decisoes(empresa_id, VAGA_DO_BANCO)
            if d.regra == REGRA_VENCIDA
        }
        vencidos = sorted(
            (
                c
                for c in self._banco.vencendo(empresa_id, hoje - timedelta(days=1))
                if c.empresa_id == empresa_id
            ),
            key=lambda c: c.id,
        )
        decisoes = []
        for candidato in vencidos:
            validade = candidato.autorizacao_valida_ate.isoformat()
            if (candidato.id, validade) in ja_registradas:
                continue
            decisao = self._decisao_vencida(candidato, validade)
            self._repositorio.salvar_decisao(decisao)
            decisoes.append(decisao)
        return decisoes

    def _aptos(self, empresa_id: str) -> list[Candidato]:
        """Todos os perfis que a busca devolve: consulta vazia, página a página."""
        vistos: dict[str, Candidato] = {}
        for pagina in range(1, MAX_PAGINAS + 1):
            lote = self._banco.buscar(empresa_id, "", pagina)
            novos = [c for c in lote if c.id not in vistos]
            if not novos:
                break
            vistos.update((c.id, c) for c in novos)
        return list(vistos.values())

    def _pode_contatar(self, candidato: Candidato, hoje: date) -> bool:
        """Confere de novo pelo estado atual: a busca não é a única guarda."""
        atual = self._banco.obter(candidato.empresa_id, candidato.id)
        if atual is None or atual.opt_out or atual.estado == EstadoBanco.REMOVIDO:
            return False
        validade = atual.autorizacao_valida_ate
        return atual.autorizou_contato and validade is not None and validade >= hoje

    def _desatualizado(self, candidato: Candidato, hoje: date) -> bool:
        if candidato.estado == EstadoBanco.DESATUALIZADO:
            return True
        return hoje - candidato.atualizado_em > self._prazo

    def _decisao_vencida(self, candidato: Candidato, validade: str) -> Decisao:
        return Decisao(
            empresa_id=candidato.empresa_id,
            vaga_id=VAGA_DO_BANCO,
            candidato_id=candidato.id,
            tipo=TipoDecisao.DESCARTAR,
            regra=REGRA_VENCIDA,
            motivo=f"autorização de contato vencida em {validade}: a pessoa sai da busca",
            responsavel=RESPONSAVEL,
            rastro_id=f"rotina_banco:{uuid.uuid4().hex}",
            entrada={"autorizacao_valida_ate": validade},
            evidencias=[],
            momento=datetime.now(UTC),
        )


def _exigir_empresa(empresa_id: str) -> None:
    if not empresa_id or not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório em toda leitura e escrita")
