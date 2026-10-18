import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { IntakeSession } from "@/api/types";
import {
  HANDOFF_KEY,
  handoffPairKey,
  INTAKE_KEY,
  refreshHandoffOnMutation,
  subscribeToIntake,
} from "./intake";

const nextTask = () => new Promise((resolve) => setTimeout(resolve, 0));

// useIntakeSession hands this listener to useSyncExternalStore, and React calls it to compare
// snapshots. Called while another component renders, it makes React update the registrar pane
// inside that render: "Cannot update a component (RegistrarPane) while rendering a different
// component (KioskPane / HeldPair)".
describe("subscribeToIntake", () => {
  it("never calls back while a component builds a query during its render", () => {
    const client = new QueryClient();
    const onChange = vi.fn();
    const unsubscribe = subscribeToIntake(client, onChange);
    // What useQueries in KioskPane and useQuery in HeldPair do while they render; the kiosk's own
    // useQuery does the same for the check-in after a Reset.
    new QueryObserver(client, { queryKey: handoffPairKey("pair-1"), enabled: false });
    new QueryObserver(client, { queryKey: INTAKE_KEY, enabled: false });
    expect(onChange).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("tells the registrar pane once the kiosk's check-in changes", async () => {
    const client = new QueryClient();
    const onChange = vi.fn();
    const unsubscribe = subscribeToIntake(client, onChange);
    client.setQueryData(INTAKE_KEY, { id: "intake-1" } as IntakeSession);
    await nextTask();
    expect(onChange).toHaveBeenCalled();
    unsubscribe();
  });

  it("ignores every other query, the held pairs included", async () => {
    const client = new QueryClient();
    const onChange = vi.fn();
    const unsubscribe = subscribeToIntake(client, onChange);
    client.setQueryData(handoffPairKey("pair-1"), { pair: { id: "pair-1" } });
    await nextTask();
    expect(onChange).not.toHaveBeenCalled();
    unsubscribe();
  });
});

describe("refreshHandoffOnMutation", () => {
  // The registrar approves on the Desk (a case mutation the kiosk does not own); the kiosk's
  // held pairs must be read again so the patient sees the done state without a reload.
  it("re-reads the held pairs after any mutation succeeds, never after one fails", async () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const stop = refreshHandoffOnMutation(client);
    const run = (fn: () => Promise<unknown>) =>
      client
        .getMutationCache()
        .build(client, { mutationFn: fn })
        .execute(undefined)
        .catch(() => undefined);

    await run(() => Promise.reject(new Error("409")));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(invalidate).not.toHaveBeenCalled();

    await run(() => Promise.resolve({ decision: { status: "LINKED" } }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: HANDOFF_KEY });

    stop();
    invalidate.mockClear();
    await run(() => Promise.resolve({}));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(invalidate).not.toHaveBeenCalled();
  });
});
