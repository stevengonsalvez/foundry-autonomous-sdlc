import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Relative, so one artifact serves from /foundry-autonomous-sdlc/ (prod) and /foundry-autonomous-sdlc/staging/.
// Safe because the app uses a hash router: it never needs to know its own path.
const PAGES_BASE = "./";

export default defineConfig(({ mode }) => {
  const pages = mode === "pages";
  const proxy = { "/api": { target: process.env["API_URL"] ?? "http://127.0.0.1:4000", changeOrigin: true } };

  return {
    base: pages ? PAGES_BASE : "/",
    plugins: [react()],
    build: { outDir: pages ? "dist-pages" : "dist" },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  };
});
