import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Ports are configurable if the defaults are taken: FRONTEND_PORT (default 5174) and
// BACKEND_URL (default http://localhost:8001, must match the uvicorn --port).
const backend = process.env.BACKEND_URL || "http://localhost:8001";
const port = Number(process.env.FRONTEND_PORT) || 5174;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port,
    strictPort: true,
    proxy: { "/api": backend },
  },
});
