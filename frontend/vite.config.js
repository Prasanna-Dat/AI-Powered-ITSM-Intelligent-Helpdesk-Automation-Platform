import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development every request to /api/... is forwarded to the FastAPI backend on port 8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
