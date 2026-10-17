import raw from "@contracts/fixtures/scenario.json";
import type { CandidatePairDetail, Entity, SafetyAlert, SessionResponse, TilesResponse } from "@/api/types";

// contracts-v1 has no timeline endpoint, so TimelineEvent is not in openapi.json yet.
// Its type is read off the fixture itself until the timeline route lands additively.
export type TimelineEvent = (typeof raw.timelineIfApproved)[number];

/** The parts of contracts/fixtures/scenario.json the UI reads. contracts/tests/test_fixtures.py
 * validates the file against the Pydantic models, so the cast below is checked upstream. */
export interface ScenarioFixture {
  registrarLabels: string[];
  session: SessionResponse;
  pair: CandidatePairDetail;
  entityIfApproved: Entity;
  timelineIfApproved: TimelineEvent[];
  alertIfApproved: SafetyAlert;
  tiles: TilesResponse;
}

export const scenario = raw as unknown as ScenarioFixture;
