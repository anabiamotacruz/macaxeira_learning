"""Mensagem para a pessoa depois da entrevista com a Nara.

Determinística e sem modelo. Leva só o título da vaga e se a equipe vai seguir com a
pessoa. Nunca mostra nota, ranking nem dado de outra pessoa. A decisão vem do
resultado da entrevista: esta função só a comunica.
"""

from backend.contato.prompts import AVISO_SIMULACAO, MARCADOR_NOME, PALAVRA_SAIDA
from backend.contratos.modelos import ResultadoEntrevista, Vaga


def mensagem_pos_entrevista(vaga: Vaga, resultado: ResultadoEntrevista) -> str:
    """Texto do retorno pós-entrevista, com o nome da pessoa no marcador `{nome}`."""
    if resultado.empresa_id != vaga.empresa_id or resultado.vaga_id != vaga.id:
        raise ValueError("o resultado não é desta vaga e empresa")
    if resultado.aprovado:
        retorno = (
            "A equipe quer seguir com você no processo e vai entrar em contato "
            "com os próximos passos."
        )
    else:
        retorno = (
            "Desta vez a equipe não vai seguir com a sua candidatura. "
            "Agradecemos o seu tempo e o interesse."
        )
    partes = [
        f"Olá, {MARCADOR_NOME}! Obrigado pela entrevista para a vaga de {vaga.titulo}.",
        retorno,
        f"Se não quiser mais receber mensagens, responda {PALAVRA_SAIDA}.",
    ]
    if resultado.simulado:
        partes.append(AVISO_SIMULACAO)
    return " ".join(partes)
