# Pesquisa de Mercado: Sourcing com IA

## 1. Escopo
* **Foco:** Vaga -> Busca (Sourcing) -> Análise/Matching -> Revisão Humana -> Convite -> Handoff à Nara.
* **Fora do escopo:** Condução de entrevistas por voz (responsabilidade dedicada da Nara).
* **Pergunta central:** Como reduzir o tempo entre abrir a vaga e apresentar candidatos qualificados, com transparência e sem viés?

## 2. Mapa de Ferramentas
| Ferramenta | Sourcing | Análise/Matching | Triagem | Contato | Entrevista | Revisão Humana | Fonte |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Gem** | Sim (800M+ perfis) | Sim (histórico interno) | Sim | Sim | Não | Sim | gem.com/blog/what-is-an-ai-sourcing-agent |
| **GoPerfect** | Sim | Sim (Score 1-5 explicável) | Sim | Sim | Não | Sim | goperfect.com |
| **Juicebox** | Sim (Agentes autônomos) | Sim (Bias-aware) | Sim | Sim | Não | Sim | juicebox.ai |
| **SeekOut** | Sim | Sim (Matching com IA) | Sim | Sim | Não | Sim | seekout.com/blog/ai-agents-for-recruiting |
| **TalentFindr** | Sim (KAIA autônomo) | Sim | Sim | Sim | Não | Sim (Passo a passo) | capterra.com (produto 1105244) |
| **Taalent** | Sim (6 Agentes) | Sim | Sim | Sim | Não | Sim (Decisão final) | noota.io/fr/fonctionnalites/recruitment-agent |

## 3. Rubrica de Avaliação (Base dos Evals)
| Dimensão | Como medir | Eliminatório? |
| --- | --- | --- |
| **Hard skills** | Validação de tecnologias do repositório/currículo vs requisitos da vaga | Sim |
| **Soft skills** | Indicadores extraídos de resumos interpessoais e cartas de apresentação | Não |
| **Experiência** | Tempo de atuação em papéis similares e complexidade de projetos | Sim |
| **Formação** | Cursos, graduações ou certificações específicas | Não |
| **Aderência à vaga** | Coincidência de domínio técnico e cultura declarada | Sim |
| **Potencial** | Velocidade de aprendizado e evolução profissional em papéis recentes | Não |

## 4. Lacunas e Diferenciação
| Ideia | Já existe? Quem? | Por que a nossa é diferente | Evidência |
| --- | --- | --- | --- |
| **Rastro de decisão auditável + Custo por candidato** | Parcialmente (GoPerfect/Gem) | Exibe o raciocínio completo da IA e o custo exato em tokens por avaliação de candidato. | Exigências de governança e viés (EU AI Act / LGPD). |
| **Handoff estruturado para a Nara** | Não | Transmite um dossier técnico estruturado direto para a agente de voz (Nara) prosseguir na entrevista. | Arquitetura modular de multi-agentes. |
| **Aprendizado por realimentação rápida** | Parcialmente | Ajustes do recrutador na revisão humana recalibram os pesos da rubrica para os próximos candidatos. | Feedback loop direto na triagem. |

## 5. Decisão de MVP
* **Entra:**
  - Sourcing e extração de perfis.
  - Scoring transparente baseado na Rubrica de Avaliação.
  - Painel de revisão humana com auditabilidade e custo em tokens.
  - Geração de pacote/dossiê de handoff para a Nara.
* **Fica fora:**
  - Condução de entrevistas por voz.
  - Integração nativa com ATS legados (Workday, Greenhouse).
  - Envio automático de mensagens sem validação humana prévia.
* **Validar com recrutadores:**
  - Legibilidade e clareza dos critérios de pontuação da rubrica.
  - Facilidade de consumo do dossiê de handoff pela equipe de entrevistas.
