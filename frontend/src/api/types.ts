// Names for the generated contract types. Every shape comes from contracts/openapi.json
// through `npm run gen:api`; nothing here is written by hand.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Band = Schemas["Band"];
export type ReasonCode = Schemas["ReasonCode"];
export type Contribution = Schemas["Contribution"];
export type SourceCard = Schemas["SourceCard"];
export type NormalizedRecord = Schemas["NormalizedRecord"];
export type MatchDecision = Schemas["MatchDecision"];
export type CandidatePairDetail = Schemas["CandidatePairDetail"];
export type ApproveRequest = Schemas["ApproveRequest"];
export type RejectRequest = Schemas["RejectRequest"];
export type ReviewRequest = ApproveRequest | RejectRequest;
export type ReviewResponse = Schemas["ReviewResponse"];
export type Entity = Schemas["Entity"];
export type GoldenField = Schemas["GoldenField"];
export type SafetyAlert = Schemas["SafetyAlert"];
export type SessionResponse = Schemas["SessionResponse"];
export type Tile = Schemas["Tile"];
export type TilesResponse = Schemas["TilesResponse"];
export type TimelineEvent = Schemas["TimelineEvent"];
export type ErrorEnvelope = Schemas["ErrorEnvelope"];
export type EventLogRow = Schemas["EventLogRow"];
export type EventType = Schemas["EventType"];
export type Language = Schemas["Language"];
export type AgentMode = Schemas["AgentMode"];
export type IntakeSession = Schemas["IntakeSession"];
export type IntakeTurn = Schemas["IntakeTurn"];
export type ToolCallRecord = Schemas["ToolCallRecord"];
export type ToolCallCandidate = Schemas["ToolCallCandidate"];
