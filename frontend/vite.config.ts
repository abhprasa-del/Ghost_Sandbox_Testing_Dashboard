import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev the API runs on :8000; in Docker nginx proxies /api so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
