import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api + /ws to the FastAPI backend so the SPA can use same-origin
// paths in code; prod serves the built SPA from backend/static (no proxy).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: {
    // Built SPA goes to backend/static so main.py serves it in production.
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
