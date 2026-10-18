// The demo runs on the local dev server; a hosted copy sets NEXT_PUBLIC_SITE_ORIGIN at build time
// so link previews resolve /og.png against the address people actually share.
export const DEFAULT_SITE_ORIGIN = "http://localhost:3000";

/** The origin Next resolves relative metadata URLs (og:image) against. A malformed value throws. */
export function siteOrigin(value: string | undefined): URL {
  return new URL(value?.trim() || DEFAULT_SITE_ORIGIN);
}
