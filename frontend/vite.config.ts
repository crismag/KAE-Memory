/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // The API has no authentication (ADR-0014), so it binds to loopback. The
    // dev proxy keeps the browser on one origin rather than opening CORS.
    proxy: { "/v1": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
