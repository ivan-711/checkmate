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
  // tsconfig keeps JSX for Next (jsx: preserve); Vite compiles it here so a test can render a component.
  oxc: { jsx: { runtime: "automatic" } },
  test: { include: ["src/**/*.test.ts"] },
});
