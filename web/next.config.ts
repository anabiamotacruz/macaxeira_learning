import type { NextConfig } from "next";

// No deploy, o painel repassa /api/* para a API do agente pela rede privada (API_INTERNA_URL,
// ex.: http://api.railway.internal:8000), atrás do login do proxy.ts. Aí NEXT_PUBLIC_API_URL=/api.
const API_INTERNA_URL = process.env.API_INTERNA_URL?.replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Esconde o botão "N" do Next no canto da tela durante o desenvolvimento (no build de produção ele já não aparece).
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
  // A proposta de vaga e as análises com o modelo podem passar de 30 s, o padrão do repasse.
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return API_INTERNA_URL ? [{ source: "/api/:path*", destination: `${API_INTERNA_URL}/:path*` }] : [];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
