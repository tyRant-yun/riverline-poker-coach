import { describe, expect, it, vi } from "vitest";

import { BeliefRequestGate } from "./beliefRequest";

describe("BeliefRequestGate", () => {
  it("accepts only the latest action response", async () => {
    const gate = new BeliefRequestGate();
    let resolveFirst: ((value: string) => void) | undefined;
    const first = new Promise<string>((resolve) => { resolveFirst = resolve; });
    const second = Promise.resolve("seat-5-current");
    const apply = vi.fn();

    const firstToken = gate.begin();
    void first.then((value) => { if (gate.isCurrent(firstToken)) apply(value); });
    const secondToken = gate.begin();
    void second.then((value) => { if (gate.isCurrent(secondToken)) apply(value); });

    await second;
    resolveFirst?.("seat-3-stale");
    await first;

    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith("seat-5-current");
  });

  it("invalidates an in-flight result when the scenario changes", () => {
    const gate = new BeliefRequestGate();
    const token = gate.begin();
    gate.invalidate();

    expect(gate.isCurrent(token)).toBe(false);
  });
});
