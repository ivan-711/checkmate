import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import type { ReactNode } from "react";
import { Header } from "@/components/ui/Header";
import "./globals.css";
import { Providers } from "./providers";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "CheckMate",
  description: "Synthetic-data prototype for identity reconciliation. Not for clinical use.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="min-h-screen font-sans text-[18px]">
        <Providers>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-10 focus:bg-surface focus:p-2"
          >
            Skip to main content
          </a>
          <p className="flex h-7 items-center bg-banner px-4 text-[16px] font-semibold text-on-banner">
            Synthetic data. Not for clinical use.
          </p>
          <Header />
          <main id="main" tabIndex={-1} className="mx-auto max-w-[1440px] p-4 outline-none">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
