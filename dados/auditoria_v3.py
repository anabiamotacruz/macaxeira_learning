"""Contagem e diagnóstico lexical; não estima precisão ou independência estatística."""

import hashlib
import json
import re
import unicodedata
from collections import Counter


def serializar(dados: object) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def _fragmentos(texto: str) -> set[tuple[str, ...]]:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    palavras = re.findall(r"[a-z]+", texto)
    return {tuple(palavras[i:i + 3]) for i in range(len(palavras) - 2)}


def auditar(candidatos: list[dict], vagas: list[dict], casos: list[dict]) -> dict:
    """Não conta pares como novos casos e aponta sobreposição de trigramas >= 0,65."""
    bases = [c for c in casos if c["conta_independencia"]]
    textos = {c["id_caso"]: candidatos[c["indice"]]["perfil_texto"] for c in bases}
    fragmentos = {chave: _fragmentos(texto) for chave, texto in textos.items()}
    semelhantes = []
    maior = 0.0
    chaves = list(fragmentos)
    for i, chave in enumerate(chaves):
        for outra in chaves[i + 1:]:
            a, b = fragmentos[chave], fragmentos[outra]
            similaridade = len(a & b) / len(a | b) if a | b else 1.0
            maior = max(maior, similaridade)
            if similaridade >= 0.65:
                semelhantes.append({"casos": [chave, outra], "jaccard": round(similaridade, 4)})
    prova = [c for c in bases if c["particao"] == "prova"
             and c["resultado_esperado"] == "indicar"]
    return {
        "versao": 3,
        "registros": len(candidatos),
        "funcoes": len({c["funcao"] for c in casos}),
        "vagas": len(vagas),
        "familias_profissionais": len({c["grupo_independencia"] for c in casos}),
        "indicaveis_prova_independentes": len({c["grupo_independencia"] for c in prova}),
        "textos_profissionais_distintos_sem_pares": len(set(textos.values())),
        "pares_vies": len({c["par_vies"] for c in casos if c["par_vies"]}),
        "por_particao": dict(Counter(c["particao"] for c in casos)),
        "por_resultado_e_particao": dict(Counter(
            f'{c["particao"]}/{c["resultado_esperado"]}' for c in casos
        )),
        "maior_jaccard_trigramas_sem_pares": round(maior, 4),
        "limiar_alerta_jaccard": 0.65,
        "pares_muito_semelhantes_sem_vies": semelhantes,
        "sha256_candidatos": hashlib.sha256(serializar(candidatos).encode()).hexdigest(),
        "sha256_vagas": hashlib.sha256(serializar(vagas).encode()).hexdigest(),
        "sha256_casos": hashlib.sha256(serializar(casos).encode()).hexdigest(),
        "validacao_rh": "pendente",
        "precisao_modelo": "nao_medida",
        "independencia_estatistica": "nao_demonstrada_por_diversidade_lexical",
    }
