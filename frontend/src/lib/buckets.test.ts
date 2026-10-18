import { describe, expect, it } from "vitest";
import { bucketStart, bucketWindowCt } from "./buckets";

describe("5-minute buckets", () => {
  it("puts a moment in the bucket that starts at or before it, as time_bucket does", () => {
    expect(bucketStart(new Date("2026-10-18T03:14:59.999Z"))).toBe("2026-10-18T03:10:00Z");
    expect(bucketStart(new Date("2026-10-18T03:15:00Z"))).toBe("2026-10-18T03:15:00Z");
  });

  it("reads a bucket as the five minutes it counted, in CT, across the hour", () => {
    expect(bucketWindowCt("2026-10-18T03:55:00Z")).toBe("22:55 to 23:00");
  });
});
