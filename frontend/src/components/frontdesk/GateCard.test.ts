import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CandidatePairDetail, Contribution, ToolCallCandidate, ToolCallRecord } from "@/api/types";
import { EvidenceRail } from "@/components/case/EvidenceRail";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { COPY } from "./copy";
import { GateCard } from "./GateCard";

/** The text of each list row, tags stripped: "Given name+0.90". */
function rows(html: string): string[] {
  return [...html.matchAll(/<li(?:\s[^>]*)?>(.*?)<\/li>/g)].map((m) => m[1].replace(/<[^>]+>/g, ""));
}

function gateRows(call: ToolCallRecord, candidate: ToolCallCandidate, language: "en" | "es" = "en") {
  return rows(renderToStaticMarkup(createElement(GateCard, { call, candidate, t: COPY[language] })));
}

function railRows(contributions: Contribution[]) {
  const detail: CandidatePairDetail = { ...scenario.pair, contributions };
  return rows(renderToStaticMarkup(createElement(EvidenceRail, { detail })));
}

async function heldCall() {
  const s = new FixtureSource(scenario);
  const { id } = await s.startIntake("EN");
  const turn = await s.sendTurn(id, scenario.frontdeskIntake.utteranceEn, "k1");
  const call = turn.toolCalls!.find((c) => c.gate.outcome === "DENY")!;
  return { call, candidate: call.candidates![0] };
}

// The corpus hero's ER pair as the API returned it: every feature on the stored pair, and the
// gate's candidate with only its top 10 by weight (TOP_CONTRIBUTIONS_IN_LIST_VIEWS).
const HERO_PAIR: Contribution[] = [
  ["given_jw", 1],
  ["given_jw_folded", 1.5],
  ["given_dl", 0.5],
  ["given_dmeta", 0.5],
  ["given_nickname", 0],
  ["given_initial", 0.3],
  ["given_token_overlap", 0.5],
  ["family_jw", 1],
  ["family_jw_folded", 1.5],
  ["family_dl", 0.5],
  ["family_dmeta", 0.7],
  ["family_token_overlap", 0.8],
  ["dob_exact", 3],
  ["dob_day_month_swap", 0],
  ["dob_year_match", 0.8],
  ["sex_match", 0],
  ["phone_match", 1.5],
  ["address_jaccard", 1.2],
  ["zip_match", 0],
  ["missing_sex", -0.1],
  ["missing_zip", -0.2],
].map(([feature, logit]) => ({ feature: feature as string, logit: logit as number, value: 1 }));
const HERO_GATE = [...HERO_PAIR].sort((a, b) => Math.abs(b.logit) - Math.abs(a.logit)).slice(0, 10);

describe("GateCard evidence rows", () => {
  it("reads the same rows, weights and order as the registrar's rail for the fixture pair", async () => {
    const { call, candidate } = await heldCall();
    const gate = gateRows(call, candidate);
    expect(gate).toEqual(railRows(scenario.pair.contributions));
    expect(gate).not.toContain("Name+2.00"); // the audit's summed row
  });

  it("matches the rail for the corpus hero, though the gate sends only its top 10 features", async () => {
    const { call, candidate } = await heldCall();
    const gate = gateRows(call, { ...candidate, topContributions: HERO_GATE });
    expect(gate).toEqual(railRows(HERO_PAIR));
    expect(gate[0]).toBe("Date of birth+3.00");
  });

  it("names every row in Spanish on the Spanish kiosk, with the same weights", async () => {
    const { call, candidate } = await heldCall();
    const es = gateRows(call, { ...candidate, topContributions: HERO_GATE }, "es");
    const en = gateRows(call, { ...candidate, topContributions: HERO_GATE });
    const weight = (row: string) => row.match(/[+-]\d+\.\d{2}$/)?.[0];
    expect(es.map(weight)).toEqual(en.map(weight));
    expect(es[0]).toBe("Fecha de nacimiento+3.00");
    for (const row of es) expect(row).not.toMatch(/name|birth|Phone|Address|ignored/);
  });

  it("shows a feature with no value as no evidence, never as a weight", async () => {
    const { call, candidate } = await heldCall();
    const missing = { feature: "phone_match", logit: 0, value: null };
    const gate = gateRows(call, { ...candidate, topContributions: [missing] });
    expect(gate).toEqual(["Phoneno evidence"]);
  });
});
