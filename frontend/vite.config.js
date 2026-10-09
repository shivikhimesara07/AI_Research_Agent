import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The backend runs on :8001 (8000 is often taken); override with BACKEND_URL.
const backend = process.env.BACKEND_URL || "http://localhost:8001";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: { "/api": backend },
  },
});
