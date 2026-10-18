// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResetButton } from "@/components/ui/ResetButton";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { CaseScreen } from "./CaseScreen";

/** The fixture with Resolve and Reset held open until the test lets them finish, so the screen
 * can be checked while a match run or a reset is in flight. */
class HeldSource extends FixtureSource {
  private releases: Array<() => void> = [];
  hold = false;

  private gate(): Promise<void> {
    return this.hold ? new Promise((done) => this.releases.push(done)) : Promise.resolve();
  }

  release() {
    this.releases.splice(0).forEach((done) => done());
  }

  override async resolve() {
    await this.gate();
    return super.resolve();
  }

  override async reset() {
    await this.gate();
    return super.reset();
  }
}

function renderCase(source: HeldSource) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DataSourceProvider source={source}>
        <ResetButton />
        <CaseScreen />
      </DataSourceProvider>
    </QueryClientProvider>,
  );
}

const button = (id: string) => screen.getByTestId(id) as HTMLButtonElement;

afterEach(cleanup);

describe("CaseScreen while a match run or a reset is in flight", () => {
  it("disables Approve, Reject and Resolve during a match run, and enables them after", async () => {
    const source = new HeldSource(scenario);
    renderCase(source);
    fireEvent.click(await screen.findByTestId("resolve-button"));
    await screen.findByTestId("candidate-pair");
    expect(button("approve-button").disabled).toBe(false);

    source.hold = true;
    fireEvent.click(button("resolve-button"));
    await waitFor(() => expect(button("approve-button").disabled).toBe(true));
    expect(button("reject-button").disabled).toBe(true);
    expect(button("resolve-button").disabled).toBe(true);
    expect(button("reset-button").disabled).toBe(true);
    expect(screen.getByTestId("candidate-pair").getAttribute("aria-busy")).toBe("true");

    await act(async () => source.release());
    await waitFor(() => expect(button("approve-button").disabled).toBe(false));
    expect(button("reject-button").disabled).toBe(false);
    expect(button("resolve-button").disabled).toBe(false);
    expect(screen.getByTestId("candidate-pair").getAttribute("aria-busy")).toBe("false");
  });

  it("disables Resolve, Approve and Reject while a reset runs", async () => {
    const source = new HeldSource(scenario);
    renderCase(source);
    fireEvent.click(await screen.findByTestId("resolve-button"));
    await screen.findByTestId("candidate-pair");

    source.hold = true;
    fireEvent.click(button("reset-button"));
    await waitFor(() => expect(button("resolve-button").disabled).toBe(true));
    expect(button("approve-button").disabled).toBe(true);
    expect(button("reject-button").disabled).toBe(true);

    await act(async () => source.release());
    await waitFor(() => expect(button("reset-button").disabled).toBe(false));
    // The new session waits for Resolve again, and Resolve is available.
    await waitFor(() => expect(button("resolve-button").disabled).toBe(false));
    expect(screen.queryByTestId("candidate-pair")).toBeNull();
  });
});
