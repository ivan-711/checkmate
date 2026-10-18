import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@contracts": path.resolve(__dirname, "../contracts"),
      "@hero": path.resolve(__dirname, "../data/scenarios/hero"),
    },
  },
  test: { include: ["src/**/*.test.ts"] },
});
