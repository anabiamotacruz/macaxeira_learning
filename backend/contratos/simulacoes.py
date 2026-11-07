"""Simulações de todas as interfaces, para as frentes trabalharem em paralelo.

Tudo aqui é determinístico, em memória e marcado como simulado. Não usa
internet, chaves nem modelo real.
"""

import hashlib
import re
from datetime import date

from pydantic import BaseModel, ValidationError

from backend.contratos.erros import FonteIndisponivel, RespostaInvalida
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Convite,
    EstadoBanco,
    Evidencia,
    PacoteNara,
    ResultadoNara,
    Vaga,
)

DATA_PADRAO = date(2026, 11, 7)


def _exigir_empresa(empresa_id: str) -> None:
    if not empresa_id or not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório em toda leitura e escrita")


def _numero_reproduzivel(*partes: str) -> float:
    """Número em [0, 1) derivado das partes, estável entre execuções."""
    digest = hashlib.sha256(":".join(partes).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def candidato_simulado(candidato_id: str, empresa_id: str, **campos) -> Candidato:
    """Candidato sintético, ativo e autorizado, para testes."""
    dados = {
        "id": candidato_id,
        "empresa_id": empresa_id,
        "nome": f"Pessoa Fictícia {candidato_id}",
        "fonte": "simulada",
        "simulado": True,
        "origem": "simulacao",
        "atualizado_em": DATA_PADRAO,
        "autorizacao_valida_ate": date(2027, 11, 7),
        "estado": EstadoBanco.ATIVO,
        "perfil_texto": "Perfil sintético",
        "atributos": {},
        "historico": [],
        "autorizou_contato": True,
    }
    dados.update(campos)
    return Candidato(**dados)


def _termos(texto: str) -> set[str]:
    return set(re.findall(r"\w+", texto.lower()))


def _combina(candidato: Candidato, consulta: str) -> bool:
    """Compara termos inteiros do perfil. O nome fica de fora para não influenciar a busca."""
    texto = " ".join([candidato.perfil_texto, *candidato.atributos.values()])
    return _termos(consulta) <= _termos(texto)


class FonteSimulada:
    """Fonte externa simulada, com paginação e falha injetável."""

    def __init__(self, candidatos: list[Candidato], por_pagina: int = 20) -> None:
        self.candidatos = candidatos
        self.por_pagina = por_pagina
        self.falhar = False

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        _exigir_empresa(empresa_id)
        if self.falhar:
            raise FonteIndisponivel("fonte simulada fora do ar")
        achados = [
            c for c in self.candidatos if c.empresa_id == empresa_id and _combina(c, consulta)
        ]
        inicio = (pagina - 1) * self.por_pagina
        return achados[inicio : inicio + self.por_pagina]


class BancoTalentosSimulado:
    """Banco de talentos em memória, isolado por empresa.

    A busca só devolve perfis ativos, autorizados, sem opt-out e com
    autorização válida em `hoje`. Quem foi removido não volta por importação.
    """

    def __init__(self, hoje: date = DATA_PADRAO) -> None:
        self.hoje = hoje
        self._perfis: dict[str, dict[str, Candidato]] = {}
        self._removidos: dict[str, set[str]] = {}
        self._contador = 0

    def _da_empresa(self, empresa_id: str) -> dict[str, Candidato]:
        _exigir_empresa(empresa_id)
        return self._perfis.setdefault(empresa_id, {})

    def _obter(self, empresa_id: str, candidato_id: str) -> Candidato:
        perfis = self._da_empresa(empresa_id)
        if candidato_id not in perfis:
            raise KeyError(candidato_id)
        return perfis[candidato_id]

    def _apto(self, candidato: Candidato) -> bool:
        return (
            candidato.estado == EstadoBanco.ATIVO
            and candidato.autorizou_contato
            and not candidato.opt_out
            and candidato.autorizacao_valida_ate is not None
            and candidato.autorizacao_valida_ate >= self.hoje
        )

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        perfis = self._da_empresa(empresa_id).values()
        aptos = [c for c in perfis if self._apto(c) and _combina(c, consulta)]
        aptos.sort(key=lambda c: c.id)
        inicio = (pagina - 1) * 20
        return aptos[inicio : inicio + 20]

    def importar(self, empresa_id: str, registros: list[dict]) -> list[Candidato]:
        perfis = self._da_empresa(empresa_id)
        importados = []
        for registro in registros:
            self._contador += 1
            candidato_id = registro.get("id", f"sim-{self._contador}")
            if candidato_id in self._removidos.get(empresa_id, set()):
                continue
            if candidato_id in perfis:
                importados.append(perfis[candidato_id])
                continue
            candidato = candidato_simulado(
                candidato_id,
                empresa_id,
                nome=registro.get("nome", f"Pessoa Fictícia {self._contador}"),
                perfil_texto=registro.get("perfil_texto", ""),
                origem=registro.get("origem", "importacao"),
                fonte="banco",
                atualizado_em=self.hoje,
                autorizacao_valida_ate=None,
                estado=EstadoBanco.PENDENTE,
                autorizou_contato=False,
            )
            perfis[candidato.id] = candidato
            importados.append(candidato)
        return importados

    def registrar_autorizacao(
        self, empresa_id: str, candidato_id: str, valida_ate: date
    ) -> Candidato:
        atual = self._obter(empresa_id, candidato_id)
        novo = atual.model_copy(
            update={
                "autorizou_contato": True,
                "autorizacao_valida_ate": valida_ate,
                "estado": EstadoBanco.ATIVO,
            }
        )
        self._perfis[empresa_id][candidato_id] = novo
        return novo

    def atualizar(self, empresa_id: str, candidato_id: str, dados: dict[str, str]) -> Candidato:
        atual = self._obter(empresa_id, candidato_id)
        novo = atual.model_copy(
            update={"atributos": {**atual.atributos, **dados}, "atualizado_em": self.hoje}
        )
        self._perfis[empresa_id][candidato_id] = novo
        return novo

    def registrar_opt_out(self, empresa_id: str, candidato_id: str) -> Candidato:
        novo = self._obter(empresa_id, candidato_id).model_copy(update={"opt_out": True})
        self._perfis[empresa_id][candidato_id] = novo
        return novo

    def remover(self, empresa_id: str, candidato_id: str) -> None:
        self._obter(empresa_id, candidato_id)
        del self._perfis[empresa_id][candidato_id]
        self._removidos.setdefault(empresa_id, set()).add(candidato_id)

    def vencendo(self, empresa_id: str, ate: date) -> list[Candidato]:
        return sorted(
            (
                c
                for c in self._da_empresa(empresa_id).values()
                if c.autorizacao_valida_ate is not None
                and c.autorizacao_valida_ate <= ate
                and not c.opt_out
                and c.estado != EstadoBanco.REMOVIDO
            ),
            key=lambda c: c.id,
        )


class AnalisadorSimulado:
    """Analisador que aprova tudo, com evidência do perfil. Use só em testes de fluxo."""

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        criterios = [*(r.id for r in vaga.requisitos), *(c.nome for c in vaga.competencias)]
        return Analise(
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            candidato_id=candidato.id,
            requisitos_ok={r.id: True for r in vaga.requisitos},
            notas={c.nome: 0.5 for c in vaga.competencias},
            evidencias=[
                Evidencia(criterio=criterio, trecho=candidato.perfil_texto, fonte=candidato.fonte)
                for criterio in criterios
            ],
            lacunas=[],
            pontos_a_aprofundar=[],
            alertas=[],
        )


class RevisorSimulado:
    """Revisor que acrescenta ressalvas fixas à análise."""

    def __init__(self, ressalvas: list[str] | None = None) -> None:
        self.ressalvas = ressalvas or []

    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise:
        return analise.model_copy(
            update={"ressalvas_revisor": [*analise.ressalvas_revisor, *self.ressalvas]}
        )


class MensageiroSimulado:
    """Mensageiro idempotente por chave, com falhas injetáveis antes e depois do envio."""

    def __init__(self, falhas_restantes: int = 0, falhas_apos_envio: int = 0) -> None:
        self.falhas_restantes = falhas_restantes
        self.falhas_apos_envio = falhas_apos_envio
        self.enviados: dict[str, Convite] = {}

    def enviar(self, convite: Convite) -> bool:
        if convite.chave_idempotencia in self.enviados:
            return True
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            return False
        self.enviados[convite.chave_idempotencia] = convite
        if self.falhas_apos_envio > 0:
            self.falhas_apos_envio -= 1
            return False
        return True


class ClienteNaraSimulado:
    """Nara simulada: link fictício, entregas idempotentes, falhas injetáveis e resultados
    reproduzíveis.
    """

    BASE_LINK = "https://nara.simulada.local/agendar"

    def __init__(self, semente: int = 0, falhas_restantes: int = 0) -> None:
        self.semente = semente
        self.falhas_restantes = falhas_restantes
        self.entregues: dict[tuple[str, str], PacoteNara] = {}

    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str:
        return f"{self.BASE_LINK}/{vaga_id}/{candidato_id}"

    def entregar(self, pacote: PacoteNara) -> bool:
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            return False
        self.entregues.setdefault((pacote.empresa_id, pacote.chave_idempotencia), pacote)
        return True

    def resultados_para(self, pacote: PacoteNara) -> ResultadoNara:
        nota = round(
            _numero_reproduzivel(
                str(self.semente), pacote.empresa_id, pacote.vaga_id, pacote.candidato_id
            ),
            2,
        )
        return ResultadoNara(
            empresa_id=pacote.empresa_id,
            vaga_id=pacote.vaga_id,
            candidato_id=pacote.candidato_id,
            notas={"geral": nota},
            aprovado=nota >= 0.5,
            simulado=True,
        )

    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoNara]:
        _exigir_empresa(empresa_id)
        return [
            self.resultados_para(p)
            for p in self.entregues.values()
            if p.empresa_id == empresa_id and p.vaga_id == vaga_id
        ]


class ClienteModeloSimulado:
    """Modelo simulado: devolve respostas fixas por etapa e registra as chamadas."""

    def __init__(self, respostas: dict[str, dict] | None = None) -> None:
        self.respostas = respostas or {}
        self.chamadas: list[dict[str, str]] = []

    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        self.chamadas.append({"sistema": sistema, "usuario": usuario, "etapa": etapa})
        if etapa not in self.respostas:
            raise RespostaInvalida(f"sem resposta simulada para a etapa {etapa!r}")
        try:
            return esquema.model_validate(self.respostas[etapa])
        except ValidationError as erro:
            raise RespostaInvalida(f"resposta simulada inválida na etapa {etapa!r}") from erro
