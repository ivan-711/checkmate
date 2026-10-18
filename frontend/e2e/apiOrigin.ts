// The API-mode e2e presses Reset demo on whatever API it targets, so it never falls back to a
// default origin: next.config.ts falls back to http://127.0.0.1:8000, where the live demo runs.
export const API_ORIGIN_VAR = "CHECKMATE_API_ORIGIN";

export function requireApiOrigin(env: Record<string, string | undefined>): string {
  const origin = env[API_ORIGIN_VAR]?.trim();
  if (!origin) {
    throw new Error(
      `${API_ORIGIN_VAR} is not set. npm run e2e:api resets the demo on the API it targets, so it ` +
        `will not default to http://127.0.0.1:8000 (the live demo). Start a scratch API and run ` +
        `${API_ORIGIN_VAR}=http://127.0.0.1:<its port> npm run e2e:api`,
    );
  }
  return origin;
}
