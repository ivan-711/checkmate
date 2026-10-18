import type { Metadata } from "next";
import type { ReactNode } from "react";
// Self-hosted at build time (CONCEPT.md §4): no font request leaves the venue's laptop.
import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource-variable/instrument-sans";
import "@fontsource/dm-mono/400.css";
import "@fontsource/dm-mono/500.css";
import { Header } from "@/components/ui/Header";
import { siteOrigin } from "@/lib/siteOrigin";
import "./globals.css";
import { Providers } from "./providers";

const PITCH = "A bilingual AI check-in kiosk that can’t open duplicate charts";

export const metadata: Metadata = {
  // Link previews resolve /og.png against this origin (the local dev server unless set).
  metadataBase: siteOrigin(process.env.NEXT_PUBLIC_SITE_ORIGIN),
  title: "CheckMate",
  description: "Synthetic-data prototype for identity reconciliation. Not for clinical use.",
  // public/, rendered by scripts/render-assets.mjs. app/icon.svg is picked up by file convention.
  manifest: "/manifest.webmanifest",
  icons: { apple: "/apple-touch-icon.png" },
  // public/og.png, rendered by scripts/render-assets.mjs from the mark and the pitch.
  openGraph: {
    title: "CheckMate",
    description: PITCH,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "CheckMate. " + PITCH }],
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // The venue runs light (DESIGN.md): the demo never follows a laptop set to dark mode.
    <html lang="en" data-theme="light">
      <body className="min-h-screen font-sans">
        <Providers>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-10 focus:bg-paper focus:p-2"
          >
            Skip to main content
          </a>
          <Header />
          <main id="main" tabIndex={-1} className="outline-none">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
