import raw from "@contracts/fixtures/scenario.json";
import type {
  CandidatePairDetail,
  Entity,
  SafetyAlert,
  SessionResponse,
  TilesResponse,
  TimelineEvent,
} from "@/api/types";

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
