import { NextResponse, type NextRequest } from "next/server";

// Login do painel no deploy: usuário e senha (HTTP Basic) em PAINEL_USUARIO e PAINEL_SENHA.
// Sem as duas variáveis (desenvolvimento local), o painel fica aberto como antes.
// Cobre também /api, o repasse para a API do agente (next.config.ts): a API não precisa de domínio público.

function iguais(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diferenca = 0;
  for (let i = 0; i < a.length; i++) diferenca |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diferenca === 0;
}

export function proxy(request: NextRequest) {
  const usuario = process.env.PAINEL_USUARIO;
  const senha = process.env.PAINEL_SENHA;
  if (!usuario || !senha) return NextResponse.next();

  const cabecalho = request.headers.get("authorization") ?? "";
  if (cabecalho.startsWith("Basic ")) {
    try {
      const [u, ...resto] = atob(cabecalho.slice(6)).split(":");
      if (iguais(u, usuario) && iguais(resto.join(":"), senha)) return NextResponse.next();
    } catch {
      // Cabeçalho malformado: pede o login de novo.
    }
  }
  return new NextResponse("Login necessário.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="CORA", charset="UTF-8"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
