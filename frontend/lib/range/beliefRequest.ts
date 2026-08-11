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
