import { describe, expect, it } from "vitest";

import {
  bigBlindValue,
  formatAmount,
  formatBigBlinds,
  formatChips,
  toBigBlinds,
} from "./format";

describe("formatBigBlinds", () => {
  it("converts chips to big blinds with a 100 BB", () => {
    expect(formatBigBlinds(150, 100)).toBe("1.5 BB");
    expect(formatBigBlinds(10000, 100)).toBe("100 BB");
    expect(formatBigBlinds(50, 100)).toBe("0.5 BB");
    expect(formatBigBlinds(200, 100)).toBe("2 BB");
    expect(formatBigBlinds(9900, 100)).toBe("99 BB");
    expect(formatBigBlinds(9750, 100)).toBe("97.5 BB");
  });

  it("handles non-standard big blinds", () => {
    expect(formatBigBlinds(600, 200)).toBe("3 BB");
    expect(formatBigBlinds(25, 200)).toBe("0.13 BB");
  });

  it("degrades safely for invalid input", () => {
    expect(formatBigBlinds(100, 0)).toBe("0 BB");
  });
});

describe("formatChips", () => {
  it("formats integers with thousands separators", () => {
    expect(formatChips(150)).toBe("150");
    expect(formatChips(10000)).toBe("10,000");
    expect(formatChips(9900)).toBe("9,900");
  });
});

describe("formatAmount / toBigBlinds / bigBlindValue", () => {
  it("defaults to BB mode and switches to chips", () => {
    expect(formatAmount(150, 100, "bb")).toBe("1.5 BB");
    expect(formatAmount(150, 100, "chips")).toBe("150");
    expect(toBigBlinds(150, 100)).toBe(1.5);
    expect(bigBlindValue(150, 100)).toBe("1.5");
    expect(bigBlindValue(200, 100)).toBe("2");
  });
});
