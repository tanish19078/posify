import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ["terminal.local"],
    proxy: {
      "/v1": {
        target: process.env.POSIFY_API_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.POSIFY_API_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: { environment: "jsdom", globals: true, restoreMocks: true },
});
