"""Revisa a análise de forma independente (T2.4), em uma chamada separada ao modelo.

O revisor só acrescenta ressalvas: nunca muda nota, evidência ou requisito. Ressalva leva a
decisão a uma pessoa e não descarta ninguém. Resposta inválida não vira aprovação: o erro segue
para `FluxoVaga`, que marca a ressalva e conta as inválidas seguidas para pausar a vaga.
"""

from pydantic import BaseModel

from backend.agente.prompts import como_dado
from backend.agente.regras import criterios_sem_evidencia
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Vaga
from backend.fontes.analisador import (
    PerfilPreparado,
    como_no_perfil,
    criterio_citado,
    criterios_da_vaga,
    descrever_vaga,
    preparar_perfil,
    texto_permitido,
    trecho_confere,
)
from backend.fontes.anonimizador import Pseudonimizador, termos_preservados_da_vaga
from backend.fontes.prompts import SISTEMA_REVISAO, USUARIO_REVISAO

ETAPA_REVISAO = "revisao"

RESSALVA_SEM_TRECHO = "revisor_ressalva_sem_trecho"
"""Ressalva que o código não confirmou: o texto sai, e a decisão vai a uma pessoa."""

RESSALVA_NOTA_SEM_EVIDENCIA = "nota_sem_evidencia"


class RessalvaModelo(BaseModel):
    criterio: str
    problema: str
    trecho: str


class RespostaRevisao(BaseModel):
    """`ressalvas` é obrigatório: resposta sem o campo não pode contar como análise sem problema."""

    ressalvas: list[RessalvaModelo]


class RevisorIndependente:
    """Implementa `Revisor`. Falhas do cliente seguem para o fluxo, que sabe tratá-las."""

    def __init__(
        self, cliente: ClienteModelo, pseudonimizador: Pseudonimizador | None = None
    ) -> None:
        self._cliente = cliente
        self._pseudonimizador = pseudonimizador or Pseudonimizador()

    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise:
        self._exigir_mesma_execucao(vaga, candidato, analise)
        perfil = preparar_perfil(
            candidato,
            pseudonimizador=self._pseudonimizador,
            preservar=termos_preservados_da_vaga(vaga),
        )
        usuario = USUARIO_REVISAO.format(
            vaga=descrever_vaga(vaga),
            perfil=como_dado(perfil.texto),
            analise=como_dado(self._descrever_analise(candidato, analise, perfil)),
        )
        resposta = self._cliente.completar(SISTEMA_REVISAO, usuario, RespostaRevisao, ETAPA_REVISAO)
        ressalvas = [
            *analise.ressalvas_revisor,
            *self._notas_sem_evidencia(vaga, candidato, analise),
            *self._ressalvas_conferidas(vaga, candidato, perfil, resposta),
        ]
        return analise.model_copy(update={"ressalvas_revisor": ressalvas})

    @staticmethod
    def _exigir_mesma_execucao(vaga: Vaga, candidato: Candidato, analise: Analise) -> None:
        if vaga.empresa_id != candidato.empresa_id or analise.empresa_id != vaga.empresa_id:
            raise ValueError("vaga, candidato e análise precisam ser da mesma empresa")
        if analise.vaga_id != vaga.id or analise.candidato_id != candidato.id:
            raise ValueError("análise precisa ser da mesma vaga e do mesmo candidato")

    @staticmethod
    def _descrever_analise(candidato: Candidato, analise: Analise, perfil: PerfilPreparado) -> str:
        """Só nota e trecho conferido. Lacunas e perguntas são a leitura do analisador."""
        linhas = [f"Nota de {nome}: {nota}" for nome, nota in analise.notas.items()]
        linhas += [
            f'Trecho citado para {e.criterio}: "{e.trecho}"'
            for e in analise.evidencias
            if trecho_confere(e.trecho, candidato, perfil)
        ]
        return "\n".join(linhas)

    @staticmethod
    def _notas_sem_evidencia(vaga: Vaga, candidato: Candidato, analise: Analise) -> list[str]:
        faltando = criterios_sem_evidencia(vaga, candidato, analise)
        return [
            f"{RESSALVA_NOTA_SEM_EVIDENCIA}: {criterio}"
            for criterio in faltando
            if criterio in analise.notas
        ]

    @staticmethod
    def _ressalvas_conferidas(
        vaga: Vaga, candidato: Candidato, perfil: PerfilPreparado, resposta: RespostaRevisao
    ) -> list[str]:
        criterios = criterios_da_vaga(vaga)
        conferidas = []
        recusou = False
        for ressalva in resposta.ressalvas:
            criterio = criterio_citado(criterios, ressalva.criterio)
            trecho = como_no_perfil(ressalva.trecho).strip()
            if (
                criterio is not None
                and texto_permitido(ressalva.problema)
                and trecho_confere(trecho, candidato, perfil)
            ):
                conferidas.append(f'{criterio}: {ressalva.problema} Trecho: "{trecho}"')
            else:
                recusou = True
        return [*conferidas, RESSALVA_SEM_TRECHO] if recusou else conferidas
