import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { IntakeSession } from "@/api/types";
import { handoffPairKey, INTAKE_KEY, subscribeToIntake } from "./intake";

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
