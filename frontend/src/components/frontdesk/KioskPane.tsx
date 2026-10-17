"use client";

import { useState } from "react";

type Language = "en" | "es";

const COPY = {
  en: {
    title: "Welcome. Let's get you checked in.",
    sub: "Type your full name and date of birth. You can write in English or Spanish.",
    disclosure:
      "FrontDesk uses Gemini to read your check-in. A registrar confirms any match to an existing chart.",
    transcript: "TRANSCRIPT",
    region: "Check-in conversation",
    empty: "Your conversation will appear here.",
    language: "Language",
  },
  es: {
    title: "Le damos la bienvenida. Registremos su llegada.",
    sub: "Escriba su nombre completo y su fecha de nacimiento. Puede escribir en español o en inglés.",
    disclosure:
      "FrontDesk usa Gemini para leer su registro. El personal de admisión confirma cualquier coincidencia con un expediente existente.",
    transcript: "CONVERSACIÓN",
    region: "Conversación de registro",
    empty: "Su conversación aparecerá aquí.",
    language: "Idioma",
  },
} as const satisfies Record<Language, Record<string, string>>;

const LANGUAGES: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

export function KioskPane() {
  const [language, setLanguage] = useState<Language>("en");
  const t = COPY[language];
  return (
    <section lang={language} aria-labelledby="kiosk-label" className="flex flex-col gap-4">
      <h2
        id="kiosk-label"
        lang="en"
        className="text-[16px] font-semibold uppercase tracking-wider text-ink-3"
      >
        Patient kiosk
      </h2>
      <div className="flex min-h-[560px] flex-col gap-4 rounded-lg border border-border-subtle bg-kiosk p-6">
        <div className="flex items-center justify-between">
          <span className="text-[24px] font-semibold">FrontDesk</span>
          <div
            role="group"
            aria-label={t.language}
            className="flex rounded-md border border-border-strong p-0.5"
          >
            {LANGUAGES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                lang={value}
                aria-pressed={language === value}
                onClick={() => setLanguage(value)}
                className={`h-10 rounded px-4 text-[16px] ${
                  language === value ? "bg-surface font-semibold text-ink-1 shadow-sm" : "text-ink-2"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[40px] font-semibold leading-[48px] tracking-tight">{t.title}</p>
          <p className="text-[20px] text-ink-2">{t.sub}</p>
          <p className="text-[16px] text-ink-3">{t.disclosure}</p>
        </div>
        <section aria-label={t.region} className="flex flex-1 flex-col border-t border-border-subtle pt-3">
          <h3 className="text-[16px] font-semibold tracking-wider text-ink-3">{t.transcript}</h3>
          <p className="m-auto text-ink-3">{t.empty}</p>
        </section>
      </div>
    </section>
  );
}
