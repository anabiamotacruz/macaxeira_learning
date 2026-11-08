// Conteúdo de exemplo da landing (design CORA, commit a1d50aa). Nomes, e-mails e links são fictícios.

export type Fala = ["p" | "c", string];

export type Conversa = {
  label: string;
  vaga: string;
  chips: string[];
  linkedin: string;
  nome: string;
  primeiroNome: string;
  iniciais: string;
  email: string;
  hora1: string;
  hora2: string;
  entrevista: string;
  wa: Fala[];
};

export const CONVERSAS = {
  python: {
    label: "Dev Python",
    vaga: "Pessoa Desenvolvedora Python",
    chips: ["Python", "APIs"],
    linkedin: "linkedin.com/in/exemplo-lucas",
    nome: "Lucas Andrade",
    primeiroNome: "Lucas",
    iniciais: "LA",
    email: "lucas.andrade@exemplo.com",
    hora1: "10:25",
    hora2: "10:31",
    entrevista: "sex, 10h",
    wa: [
      ["p", "Oi! Cliquei no link do e-mail. A vaga é remota?"],
      ["c", "Oi, Lucas! É híbrida em Recife, dois dias no escritório. Hoje você trabalha mais com APIs ou com dados?"],
      ["p", "Mais com APIs, FastAPI no dia a dia."],
      ["c", "Ótimo, é o centro da vaga. Quando você conseguiria começar?"],
      ["p", "Em 15 dias."],
      ["c", "Perfeito. Escolha um horário com a Nara, que conduz a entrevista: agenda.nara.exemplo/022-lucas"],
    ],
  },
  backend: {
    label: "Backend Sênior",
    vaga: "Pessoa Desenvolvedora Backend Sênior",
    chips: ["Go", "Kafka", "Liderança técnica"],
    linkedin: "linkedin.com/in/exemplo-larissa",
    nome: "Larissa Rocha",
    primeiroNome: "Larissa",
    iniciais: "LR",
    email: "larissa.rocha@exemplo.com",
    hora1: "9:02",
    hora2: "9:14",
    entrevista: "qui, 14h",
    wa: [
      ["p", "Oi! Vim pelo e-mail. A vaga é remota mesmo?"],
      ["c", "É sim, com um encontro por mês em Recife. Hoje você prefere liderar tecnicamente ou também gerir pessoas?"],
      ["p", "Liderar tecnicamente. Gestão não é meu momento."],
      ["c", "Faz sentido, e é exatamente o desenho da vaga. Quando você conseguiria começar?"],
      ["p", "Uns 30 dias."],
      ["c", "Perfeito. Escolha um horário com a Nara, que conduz a entrevista: agenda.nara.exemplo/014-larissa"],
    ],
  },
  design: {
    label: "Product Designer",
    vaga: "Product Designer Pleno",
    chips: ["Pesquisa com usuários", "Apps financeiros"],
    linkedin: "linkedin.com/in/exemplo-ana",
    nome: "Ana Beatriz Souza",
    primeiroNome: "Ana",
    iniciais: "AS",
    email: "ana.souza@exemplo.com",
    hora1: "10:31",
    hora2: "10:40",
    entrevista: "ter, 11h",
    wa: [
      ["p", "Oi! Quantos dias no escritório?"],
      ["c", "Dois por semana, terça e quinta. Hoje você trabalha mais com pesquisa ou com interface?"],
      ["p", "Metade a metade, mas quero puxar mais pesquisa."],
      ["c", "Boa notícia: a vaga tem pesquisa com usuários todo trimestre. Posso mandar o link para você escolher um horário?"],
      ["p", "Pode sim!"],
      ["c", "Aqui: agenda.nara.exemplo/021-ana. A Nara já recebe o seu contexto, não precisa repetir nada."],
    ],
  },
  dados: {
    label: "Analista de Dados",
    vaga: "Analista de Dados Pleno",
    chips: ["dbt", "Airflow", "SQL"],
    linkedin: "linkedin.com/in/exemplo-rafael",
    nome: "Rafael Lima",
    primeiroNome: "Rafael",
    iniciais: "RL",
    email: "rafael.lima@exemplo.com",
    hora1: "18:05",
    hora2: "18:22",
    entrevista: "seg, 16h",
    wa: [
      ["p", "Oi. Qual a faixa salarial?"],
      ["c", "A faixa é de R$ 9 mil a R$ 12 mil e está no material da vaga. Quer que eu mande a descrição completa?"],
      ["p", "Manda. E o time tem quantas pessoas?"],
      ["c", "Seis, com uma liderança técnica. Acabei de mandar a descrição no seu e-mail também."],
      ["p", "Curti. Como sigo?"],
      ["c", "Escolha um horário com a Nara por aqui: agenda.nara.exemplo/017-rafael"],
    ],
  },
  vendas: {
    label: "Vendas B2B",
    vaga: "Executiva de Vendas B2B",
    chips: ["SaaS para RH", "Vendas consultivas"],
    linkedin: "linkedin.com/in/exemplo-carla",
    nome: "Carla Mendes",
    primeiroNome: "Carla",
    iniciais: "CM",
    email: "carla.mendes@exemplo.com",
    hora1: "14:12",
    hora2: "14:30",
    entrevista: "qua, 9h",
    wa: [
      ["p", "Oi! Tenho interesse, mas estou em outro processo seletivo."],
      ["c", "Sem problema, obrigada por avisar. Prefere seguir em paralelo ou que eu volte a falar daqui a um mês?"],
      ["p", "Pode seguir em paralelo."],
      ["c", "Combinado, vou deixar isso anotado para a entrevista. Ficou alguma dúvida sobre a vaga?"],
      ["p", "Não, tudo certo."],
      ["c", "Então escolha um horário com a Nara: agenda.nara.exemplo/019-carla"],
    ],
  },
} satisfies Record<string, Conversa>;

export type Cargo = keyof typeof CONVERSAS;
export const CARGOS = Object.keys(CONVERSAS) as Cargo[];

/** O que a CORA anota para a entrevista: rótulo, valor e o passo da demo em que aparece. */
export const ANOTACOES: Record<Cargo, Array<[string, string, number]>> = {
  python: [["Modelo de trabalho", "Híbrido em Recife, 2 dias", 3], ["Stack", "APIs com FastAPI", 4], ["Disponibilidade", "15 dias", 6], ["Próximo passo", "Link da Nara enviado", 7]],
  backend: [["Modelo de trabalho", "Remoto, 1 encontro por mês", 3], ["Momento", "Liderança técnica, sem gestão", 4], ["Disponibilidade", "30 dias", 6], ["Próximo passo", "Link da Nara enviado", 7]],
  design: [["Modelo de trabalho", "Híbrido, terça e quinta", 3], ["Interesse", "Quer puxar mais pesquisa", 4], ["Combinado", "Topou a entrevista", 6], ["Próximo passo", "Link da Nara enviado", 7]],
  dados: [["Dúvida", "Faixa salarial", 3], ["Enviado", "Descrição completa por e-mail", 5], ["Combinado", "Quer seguir", 6], ["Próximo passo", "Link da Nara enviado", 7]],
  vendas: [["Contexto", "Em outro processo seletivo", 2], ["Combinado", "Seguir em paralelo", 4], ["Para a entrevista", "Perguntar sobre o outro processo", 5], ["Próximo passo", "Link da Nara enviado", 7]],
};

export const FASES = ["E-mail enviado", "Clique no e-mail", "Conversa no WhatsApp", "Entrevista marcada"];

export const IDEIAS: Array<{ rotulo: string; texto: string }> = [
  { rotulo: "Backend sênior remoto", texto: "Backend sênior, Go ou Python, 5+ anos com filas. Remoto. Não abordar quem trabalha na Vértice Pagamentos." },
  { rotulo: "Designer em Recife", texto: "Product Designer pleno em Recife, com portfólio de app financeiro." },
  { rotulo: "Reativar o banco", texto: "Reative quem autorizou o banco em 2025 e combina com Dados Pleno." },
  { rotulo: "Dados com dbt", texto: "Engenheira de dados que já usou dbt e Airflow, híbrido em São Paulo." },
  { rotulo: "Respeitar a blacklist", texto: "Ignore perfis da Lumen Saúde e da Orla Logística nesta vaga." },
];

export type Tom = "atende" | "parcial" | "lacuna" | "nao";

export type Situacao = {
  label: string;
  tom: "ok" | "warn" | "coral";
  texto: string;
  nome: string;
  iniciais: string;
  email: string;
  nota: string;
  criterios: Array<{ nome: string; tom: Tom; pct: number }>;
  notaTitulo: string;
  notaTexto: string;
  rastro: string;
};

export const SITUACOES = {
  autorizada: {
    label: "Autorizada",
    tom: "ok",
    texto: "Autorizou o uso dos dados. Entra na busca e pode receber o convite para a vaga.",
    nome: "Larissa Rocha",
    iniciais: "LR",
    email: "larissa.rocha@exemplo.com · Recife",
    nota: "92",
    criterios: [
      { nome: "Go ou Python em produção", tom: "atende", pct: 96 },
      { nome: "Filas e mensageria", tom: "atende", pct: 90 },
      { nome: "Liderança técnica", tom: "parcial", pct: 68 },
      { nome: "Observabilidade", tom: "lacuna", pct: 32 },
    ],
    notaTitulo: "Evidência.",
    notaTexto: "Liderou a migração para Kafka numa fintech, de 2022 a 2024. Fonte: LinkedIn.",
    rastro: "revisor aprovou · rastro a91f",
  },
  aguardando: {
    label: "Aguardando autorização",
    tom: "warn",
    texto: "Perfil novo ou com autorização vencida. Recebe só o pedido de autorização e fica fora da busca até responder.",
    nome: "Tiago Moura",
    iniciais: "TM",
    email: "tiago.moura@exemplo.com · Fortaleza",
    nota: "87",
    criterios: [
      { nome: "Go ou Python em produção", tom: "atende", pct: 92 },
      { nome: "Filas e mensageria", tom: "atende", pct: 84 },
      { nome: "Liderança técnica", tom: "parcial", pct: 60 },
      { nome: "Observabilidade", tom: "atende", pct: 80 },
    ],
    notaTitulo: "Próximo passo.",
    notaTexto: "Pedido de autorização enviado ontem. O convite para a vaga só sai depois do sim.",
    rastro: "autorização pendente · rastro 7c02",
  },
  descartada: {
    label: "Descartada",
    tom: "coral",
    texto: "Não atende a um requisito eliminatório ou trabalha numa empresa da blacklist. O motivo fica salvo para auditoria.",
    nome: "Bruno Castro",
    iniciais: "BC",
    email: "bruno.castro@exemplo.com · Natal",
    nota: "–",
    criterios: [
      { nome: "Go ou Python em produção", tom: "atende", pct: 88 },
      { nome: "Filas e mensageria", tom: "nao", pct: 12 },
      { nome: "Liderança técnica", tom: "lacuna", pct: 30 },
      { nome: "Observabilidade", tom: "lacuna", pct: 25 },
    ],
    notaTitulo: "Regra E-03.",
    notaTexto: "Filas e mensageria é eliminatório nesta vaga e não há evidência no perfil.",
    rastro: "descarte registrado · rastro 3e9b",
  },
} satisfies Record<string, Situacao>;

export type ChaveSituacao = keyof typeof SITUACOES;
