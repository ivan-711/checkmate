// agent_gate_5m counts agent actions by time_bucket('5 minutes', occurred_at): each row is the
// five minutes that start at its bucket time.
export const GATE_BUCKET_MS = 5 * 60_000;

/** The bucket `at` falls in, written as the API writes it: "2026-10-18T03:10:00Z". */
export function bucketStart(at: Date): string {
  const start = Math.floor(at.getTime() / GATE_BUCKET_MS) * GATE_BUCKET_MS;
  return new Date(start).toISOString().replace(".000Z", "Z");
}

const CT_MINUTE = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** The five minutes a bucket counted, in CT: "22:10 to 22:15". */
export function bucketWindowCt(bucket: string): string {
  const start = new Date(bucket);
  const end = new Date(start.getTime() + GATE_BUCKET_MS);
  return `${CT_MINUTE.format(start)} to ${CT_MINUTE.format(end)}`;
}
