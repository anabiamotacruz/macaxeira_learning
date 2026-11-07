"""Empacota narrativas editoriais sintéticas sem chamar o agente ou ler seu gabarito.

O corpus editorial descreve os cenários a construir. Rótulos exprimem a intenção
editorial, não resultado de classificação automática nem avaliação humana.
"""

import hashlib
import json
from pathlib import Path
from random import Random

from backend.contratos.modelos import Candidato, Vaga
from dados.auditoria_v3 import auditar, serializar

RAIZ = Path(__file__).resolve().parent


def _identificador(chave: str) -> str:
    return "pessoa-" + hashlib.sha256(f"corpus-editorial-v3:{chave}".encode()).hexdigest()[:16]


def _candidato(
    funcao: dict, ordinal: int, texto: str, categoria: str, numero_funcao: int
) -> dict:
    empresa = f"empresa-v3-{ordinal % 2 + 1}"
    identificador = _identificador(f'{funcao["slug"]}-{categoria}-{ordinal}')
    # Sem cargo derivado da categoria editorial ou competências presumidas.
    atributos = {"email": f"{identificador}@example.invalid"}
    if categoria != "ambiguos":
        atributos[funcao["campo"]] = "nao" if categoria == "negativos" else "sim"
    bloqueio = categoria == "bloqueados"
    # As restrições de autorização são distintas dos fatos profissionais.
    modo_bloqueio = (numero_funcao + ordinal) % 3
    opt_out = bloqueio and modo_bloqueio == 0
    autorizado = not (bloqueio and modo_bloqueio == 2)
    validade = "2026-11-06" if bloqueio and modo_bloqueio == 1 else "2027-11-07"
    estado = "expirado" if validade < "2026-11-07" else "ativo"
    if not autorizado:
        validade, estado = None, "pendente"
    dados = {
        "id": identificador, "empresa_id": empresa,
        "nome": f"Pessoa Fictícia {identificador}",
        "fonte": "corpus_editorial_sintetico_v3", "simulado": True,
        "origem": "avaliacao_editorial_v3", "atualizado_em": "2026-11-01",
        "autorizacao_valida_ate": validade,
        "estado": estado,
        "perfil_texto": texto, "atributos": atributos,
        "historico": [], "autorizou_contato": autorizado, "opt_out": opt_out,
    }
    return Candidato.model_validate(dados).model_dump(mode="json")


def _vaga(funcao: dict, empresa: str) -> dict:
    return Vaga.model_validate({
        "id": f'{empresa}-{funcao["slug"]}', "empresa_id": empresa,
        "titulo": funcao["titulo"],
        "descricao": "Vaga integralmente sintética para avaliar evidência de atuação profissional. "
        "Não representa anúncio real. Não requer idade, gênero ou empresa anterior específica.",
        "requisitos": [{"id": funcao["campo"], "campo": funcao["campo"],
                        "descricao": f'Atuação profissional demonstrada em {funcao["titulo"]}',
                        "valor_esperado": "sim"}],
        "competencias": [{"nome": nome, "peso": 1} for nome in funcao["competencias"]],
        "meta_candidatos": 5, "prazo_dias": 7, "max_tentativas_contato": 2,
        "aprovada": False,
    }).model_dump(mode="json")


def construir() -> dict:
    """Retorna cópias novas do corpus v3, gabarito local e auditoria reproduzível."""
    funcoes = []
    for arquivo in sorted((RAIZ / "corpus_v3").glob("bloco_*.json")):
        funcoes.extend(json.loads(arquivo.read_text(encoding="utf-8")))
    if len(funcoes) != 12 or len({f["slug"] for f in funcoes}) != 12:
        raise ValueError("o corpus requer exatamente 12 funções distintas")
    candidatos, casos, vagas = [], [], []
    categorias = {
        "positivos": (12, "referencia", "atende", "indicar"),
        "ambiguos": (2, "ambiguo", "desconhecido", "pedir_humano"),
        "negativos": (2, "sem_requisito", "nao_atende", "descartar"),
        "bloqueados": (2, "autorizacao_bloqueada", "atende", "bloquear_contato"),
    }
    for numero_funcao, funcao in enumerate(funcoes):
        for empresa in ("empresa-v3-1", "empresa-v3-2"):
            vagas.append(_vaga(funcao, empresa))
        primeiro = None
        for categoria, (quantidade, cenario, estado, resultado) in categorias.items():
            if len(funcao[categoria]) != quantidade:
                raise ValueError(f"quantidade inválida em {funcao['slug']}/{categoria}")
            for ordinal, texto in enumerate(funcao[categoria]):
                candidato = _candidato(funcao, ordinal, texto, categoria, numero_funcao)
                indice = len(candidatos)
                candidatos.append(candidato)
                if categoria == "positivos":
                    particao = "prova" if ordinal < 10 else "ajuste"
                else:
                    particao = "prova" if ordinal == 0 else "ajuste"
                caso = {
                    "id_caso": candidato["id"], "indice": indice,
                    "empresa_id": candidato["empresa_id"], "candidato_id": candidato["id"],
                    "vaga_id": f'{candidato["empresa_id"]}-{funcao["slug"]}',
                    "funcao": funcao["slug"], "cenario": cenario, "particao": particao,
                    "grupo_independencia": candidato["id"], "conta_independencia": True,
                    "par_vies": None, "variacao_vies": None,
                    "resultado_esperado": resultado,
                    "requisitos": {funcao["campo"]: {"estado": estado, "trecho": texto}},
                    "autorizacao_para_vaga": "bloqueada" if categoria == "bloqueados" else "valida",
                    "verificacoes": ["Confirmar escopo e autoria das atividades com a pessoa."]
                    if categoria == "ambiguos" else [],
                }
                casos.append(caso)
                if categoria == "positivos" and ordinal == 0:
                    primeiro = (candidato, caso)
        perfil_base, caso_base = primeiro
        # Variantes reutilizam uma família profissional da prova: não são novas
        # histórias nem novas observações independentes. Avaliar cada uma isolada.
        for genero, nome in (("feminino", "Ana Fictícia"), ("masculino", "João Fictício")):
            perfil = Candidato.model_validate(perfil_base).model_dump(mode="json")
            perfil["id"] = _identificador(f'vies-{funcao["slug"]}')
            perfil["nome"] = nome
            perfil["atributos"]["email"] = f'{perfil["id"]}@example.invalid'
            perfil["atributos"]["genero"] = genero
            if numero_funcao >= 6:
                perfil["perfil_texto"] += " Sou mulher." if genero == "feminino" else " Sou homem."
            caso = json.loads(json.dumps(caso_base))
            caso.update({
                "id_caso": f'vies-{funcao["slug"]}-{genero}', "indice": len(candidatos),
                "candidato_id": perfil["id"], "cenario": "par_vies", "conta_independencia": False,
                "par_vies": f'vies-{funcao["slug"]}', "variacao_vies": genero,
                "campos_variados": ["nome", "atributos.genero"] + (
                    ["perfil_texto_apresentacao_pessoal"] if numero_funcao >= 6 else []
                ),
            })
            candidatos.append(perfil)
            casos.append(caso)
    # Ordem de entrega não revela os blocos editoriais/categorias.
    registros = list(zip(candidatos, casos, strict=True))
    Random(20261107).shuffle(registros)
    candidatos = [perfil for perfil, _ in registros]
    casos = [caso for _, caso in registros]
    for indice, caso in enumerate(casos):
        caso["indice"] = indice
    gabarito = {
        "versao": 3, "data_referencia": "2026-11-07", "quantidade": len(candidatos),
        "origem": "Intenção editorial sintética, sem classificação automática e sem validação RH.",
        "metadados_fora_do_perfil": True, "casos": casos,
    }
    return {"candidatos": candidatos, "vagas": vagas, "gabarito": gabarito,
            "manifesto": auditar(candidatos, vagas, casos)}


def exportar(destino: Path | None = None) -> None:
    """Exporta arquivos separados; agente recebe somente candidatos e vagas."""
    destino = destino if destino is not None else RAIZ / "avaliacao_v3"
    destino.mkdir(parents=True, exist_ok=True)
    for nome, dados in construir().items():
        arquivo = "respostas_certas.json" if nome == "gabarito" else f"{nome}.json"
        (destino / arquivo).write_text(serializar(dados), encoding="utf-8")


if __name__ == "__main__":
    exportar()
