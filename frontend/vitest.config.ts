import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // tsconfig keeps JSX as written for Next; component tests need it compiled.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@contracts": path.resolve(__dirname, "../contracts"),
      "@hero": path.resolve(__dirname, "../data/scenarios/hero"),
    },
  },
  test: { include: ["src/**/*.test.{ts,tsx}"] },
});
