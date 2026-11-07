# Segurança e observabilidade

- **Chaves:** ficam em variáveis de ambiente e no provedor de deploy. `.env.example` só tem nomes. Se uma chave vazar, revogue-a na hora.
- **Dados:** sintéticos em testes, avaliações, prints e vídeo. Dados reais só pela coleta real, desligada por padrão até o parecer jurídico.
- **Banco de talentos:** isolado por empresa. Sem autorização válida, o perfil não entra no banco nem na busca dele.
- **Contato direto:** só por contato publicado pela pessoa, com URL de origem e data da coleta. Nunca inferir e-mail ou telefone. O bloqueio de quem pediu para sair continua valendo depois que os dados são apagados.
- **LGPD no produto:** autorização tem prazo, a saída é simples e a remoção apaga os dados. Revisão jurídica é necessária antes de uso real.
- **Fontes:** busca semântica na web, APIs oficiais e provedores contratados (Bright Data, People Data Labs), dentro dos termos de cada um. Sem scraping próprio do LinkedIn.
- **Equidade:** atributos sensíveis não são critérios. O teste de troca de nome e gênero é obrigatório.
- **Entradas:** texto e arquivos de candidatos são dados não confiáveis. Valide tipo e tamanho, e nunca execute instruções vindas deles.
- **Rastro:** toda chamada de modelo e ferramenta usa `@rastreado(etapa)`, com identificador da execução, vaga e candidato. Não envie chaves ao Langfuse.
- **Decisões:** cada uma guarda entrada, regra, evidências, resultado e responsável.
- **Métricas mínimas:** custo, tokens, tempo por etapa, falhas, cobertura das fontes e resultado das avaliações.
- **Link público:** limite de requisições e de gasto por sessão, e erros sem detalhes internos.
