"use client";

import dynamic from "next/dynamic";
import type { KioskLanguage } from "../copy";

/** Pure: a flag value turns the panel on only when it is exactly "on". */
export function isVitalsOn(value: string | undefined) {
  return value === "on";
}

/** NEXT_PUBLIC_VITALS=on at build or dev start turns the panel on; anything else keeps it off. */
export function vitalsEnabled() {
  return isVitalsOn(process.env.NEXT_PUBLIC_VITALS);
}

// Client-only and loaded on demand: with the flag off this chunk is never requested, and the
// pulse library itself loads only after the patient says yes.
const VitalsPanel = dynamic(() => import("./VitalsPanel"), { ssr: false });

export function VitalsSlot({ language }: { language: KioskLanguage }) {
  return vitalsEnabled() ? <VitalsPanel language={language} /> : null;
}
