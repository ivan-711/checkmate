import path from "node:path";
import type { NextConfig } from "next";

// The browser always calls /api/v1 on this origin; Next forwards it to FastAPI so the
// app stays same-origin and the API never needs a wildcard CORS rule.
const API_ORIGIN = process.env.CHECKMATE_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The fixture is read from contracts/ at the repo root, one level above this app.
  outputFileTracingRoot: path.join(__dirname, ".."),
  // The API-mode e2e build (playwright.api.config.ts) gets its own folder so it never replaces
  // the build a running server is serving.
  distDir: process.env.CHECKMATE_DIST_DIR ?? ".next",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_ORIGIN}/api/v1/:path*` }];
  },
};

export default nextConfig;
