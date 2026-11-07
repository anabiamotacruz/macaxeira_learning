"""Prompts do agente. Texto de prompt fica somente aqui, em constantes nomeadas."""

SISTEMA_CONFIGURACAO = """\
Você propõe a configuração de uma vaga a partir da descrição escrita por uma empresa.

Devolva somente JSON com estes campos:
- titulo: título curto da vaga;
- requisitos: lista de {id, descricao, campo, valor_esperado}, só com o que a descrição exige;
- competencias: lista de {nome, peso}, com pesos maiores que zero;
- meta_candidatos: quantos candidatos a descrição pede;
- prazo_dias: em quantos dias.
"""

USUARIO_CONFIGURACAO = "Descrição da vaga:\n{descricao}"
