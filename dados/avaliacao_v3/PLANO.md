# Corpus de avaliação v3 — plano de implementação

Objetivo: substituir o uso da base repetitiva como prova por narrativas editoriais
sintéticas distintas, sem alterar contratos nem apagar fixtures de regressão.

- [x] Escrever testes de volume indicável da prova (mínimo 100 famílias), diversidade
  de funções/textos, casos ambíguos, evidências, partições e pares de viés.
- [x] Observar falha antes de implementar o empacotador.
- [x] Redigir 12 funções × 18 relatos: 12 positivos, 2 ambíguos, 2 negativos e
  2 profissionais positivos com autorização bloqueada. Três arquivos editoriais
  independentes, 4 funções por bloco. Nenhum texto deriva de nome/ID/projeto aleatório.
- [x] Empacotar 120 positivos de prova e 24 de ajuste. Os demais casos se dividem
  entre prova e ajuste; grupos profissionais nunca atravessam partições.
- [x] Acrescentar 12 pares de viés (24 variantes): somente nome e gênero variam,
  mesma identidade dentro do par; pares não aumentam o denominador independente.
- [x] Exportar candidatos/vagas/gabarito separados e manifesto de hashes e contagens.
  Metadados de avaliação, partição e par_vies ficam somente no gabarito.
- [x] Auditar semelhança lexical entre narrativas sem variantes e evidências literais;
  revisar manualmente variedade e consistência dos relatos. Não usar essa auditoria
  como prova de independência estatística ou de precisão do modelo.
- [x] Rodar regressões completas, lint e avaliações locais; revisão independente.
- [x] Documentar limites e protocolo de congelamento.
- [x] Preparar entrega revisada para commit, push e PR.

O corpus e os rótulos são autorados para o teste; não são resultados de classificação
nem validação por RH. O empacotador não chama modelos, fontes ou regras do agente.
Ter 120 narrativas indicáveis rotuladas não certifica uma meta de 95%. O resultado
precisa ser medido sem ajuste na prova, com incerteza e revisão humana dos rótulos.
