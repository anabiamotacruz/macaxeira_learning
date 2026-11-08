import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Esconde o botão "N" do Next no canto da tela durante o desenvolvimento (no build de produção ele já não aparece).
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
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
