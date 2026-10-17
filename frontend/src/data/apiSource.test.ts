import { describe, expect, it } from "vitest";
import { ApiSource } from "./apiSource";

describe("ApiSource", () => {
  it("reports LOCAL and does not offer Undo reset (the contract has no restore route)", async () => {
    const source = new ApiSource();
    expect(source.mode).toBe("LOCAL");
    expect(source.canRestore).toBe(false);
    await expect(source.restore()).rejects.toMatchObject({ code: "NOT_IMPLEMENTED" });
  });
});
