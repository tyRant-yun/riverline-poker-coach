/**
 * Monotonic request gate for Range Belief. Fetch cannot always be aborted by
 * a transport, so consumers must also check the token before committing UI.
 */
export class BeliefRequestGate {
  private revision = 0;

  begin(): number {
    this.revision += 1;
    return this.revision;
  }

  invalidate(): void {
    this.revision += 1;
  }

  isCurrent(token: number): boolean {
    return token === this.revision;
  }
}

/**
 * The backend owns the exact node checks.  This selector merely opts HU and
 * 8-max requests into its versioned curated provider; unsupported nodes still
 * return an honest `no_policy` response from that provider.
 */
export function selectCuratedPreflopPolicy(tableSize: number):
  | { source: "preflop_policy" }
  | undefined {
  return tableSize === 2 || tableSize === 8
    ? { source: "preflop_policy" }
    : undefined;
}
