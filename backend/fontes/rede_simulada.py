"""Fonte de talentos inteiramente sintética, paginada e com falhas controladas."""

import logging
import re
from collections import defaultdict
from datetime import date
from threading import RLock

from backend.contratos.erros import FonteIndisponivel
from backend.contratos.modelos import Candidato, EstadoBanco
from backend.fontes.consultas import _normalizar, _tem_sensivel

logger = logging.getLogger(__name__)
_ESTADOS = {
    EstadoBanco.REMOVIDO: 0, EstadoBanco.EXPIRADO: 1, EstadoBanco.PENDENTE: 2,
    EstadoBanco.DESATUALIZADO: 3, EstadoBanco.ATIVO: 4,
}
_CAMPOS_BUSCAVEIS = {
    "cargo", "competencias", "habilidades", "skills", "tecnologias", "linguagens", "cloud",
}


def remover_duplicatas(candidatos: list[Candidato]) -> list[Candidato]:
    """Agrupa por empresa/id; restrições de todas as fontes continuam valendo.

    Não associa pessoas diferentes por nome ou e-mail. O conteúdo mais recente é
    preservado; campos estruturados conflitantes ficam desconhecidos. O chamador
    deve reunir as páginas/fontes antes de aplicar esta função entre fontes.
    """
    grupos: dict[tuple[str, str], list[Candidato]] = defaultdict(list)
    for candidato in candidatos:
        valido = Candidato.model_validate(candidato.model_dump())
        grupos[valido.empresa_id, valido.id].append(valido)
    resultado = []
    for chave in sorted(grupos):
        grupo = grupos[chave]
        atual = sorted(grupo, key=lambda p: (-p.atualizado_em.toordinal(), p.fonte, p.origem))[0]
        copia = atual.model_copy(deep=True)
        copia.opt_out = any(p.opt_out for p in grupo)
        copia.autorizou_contato = all(p.autorizou_contato for p in grupo)
        validades = [p.autorizacao_valida_ate for p in grupo]
        copia.autorizacao_valida_ate = min(validades) if None not in validades else None
        copia.estado = min((p.estado for p in grupo), key=_ESTADOS.__getitem__)
        copia.atributos = {
            campo: valor for campo, valor in atual.atributos.items()
            if all(p.atributos.get(campo) == valor for p in grupo)
        }
        resultado.append(copia)
    return resultado


def _termos(texto: str) -> set[str]:
    return set(re.findall(r"\.net\b|[^\W_]+(?:[+#]+|(?:[.-][^\W_]+)*)", _normalizar(texto)))


def _combina(candidato: Candidato, consulta: str) -> bool:
    valores = [valor for chave, valor in candidato.atributos.items()
               if _normalizar(chave) in _CAMPOS_BUSCAVEIS]
    return _termos(consulta) <= _termos(" ".join([candidato.perfil_texto, *valores]))


def _registrar(empresa: str, pagina: int, regra: str, quantidade: int = 0) -> None:
    logger.info(
        "Busca em rede simulada registrada",
        extra={"empresa_id": empresa, "etapa": "buscar_rede_simulada", "pagina": pagina,
               "regra": regra, "quantidade": quantidade, "simulado": True},
    )


class RedeSimulada:
    """Implementa FonteCandidatos sem rede, modelo ou contatos reais.

    Cada chamada válida consome uma tentativa, inclusive falhas injetadas.
    Limite alcançado gera FonteIndisponivel; lista vazia significa fim da busca.
    """

    def __init__(
        self, candidatos: list[Candidato], *, hoje: date, por_pagina: int = 20,
        falhas_restantes: int = 0, limite_chamadas: int | None = None,
    ) -> None:
        for valor, minimo in ((por_pagina, 1), (falhas_restantes, 0)):
            if type(valor) is not int or valor < minimo:
                raise ValueError("paginação e falhas devem ser inteiros nos limites permitidos")
        if limite_chamadas is not None and (
            type(limite_chamadas) is not int or limite_chamadas < 0
        ):
            raise ValueError("limite_chamadas deve ser inteiro não negativo ou None")
        if any(not p.simulado for p in candidatos):
            raise ValueError("a rede simulada aceita somente dados sintéticos")
        self._candidatos = remover_duplicatas(candidatos)
        self.hoje = hoje
        self.por_pagina = por_pagina
        self.falhas_restantes = falhas_restantes
        self.limite_chamadas = limite_chamadas
        self.chamadas = 0
        self._trava = RLock()

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if not isinstance(empresa_id, str) or not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório")
        if type(pagina) is not int or pagina < 1:
            raise ValueError("pagina deve ser inteiro positivo")
        if not isinstance(consulta, str) or len(consulta) > 1000:
            raise ValueError("consulta deve ser texto de até 1000 caracteres")
        if _tem_sensivel(consulta):
            raise ValueError("critério sensível não pode ser usado em consultas")
        empresa_id = empresa_id.strip()
        with self._trava:
            if self.limite_chamadas is not None and self.chamadas >= self.limite_chamadas:
                _registrar(empresa_id, pagina, "limite_simulado")
                raise FonteIndisponivel("limite de chamadas da fonte simulada atingido")
            self.chamadas += 1
            if self.falhas_restantes:
                self.falhas_restantes -= 1
                _registrar(empresa_id, pagina, "falha_simulada")
                raise FonteIndisponivel("fonte simulada temporariamente indisponível")
            candidatos = [p for p in self._candidatos if (
                p.empresa_id == empresa_id and not p.opt_out and p.autorizou_contato
                and p.autorizacao_valida_ate is not None and p.autorizacao_valida_ate >= self.hoje
                and p.estado in {EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO}
                and _combina(p, consulta)
            )]
            inicio = (pagina - 1) * self.por_pagina
            resultado = [
                p.model_copy(deep=True) for p in candidatos[inicio:inicio + self.por_pagina]
            ]
            for perfil in resultado:
                perfil.fonte = "rede_simulada"
            _registrar(empresa_id, pagina, "consulta_lexical_e_autorizacao", len(resultado))
            return resultado
