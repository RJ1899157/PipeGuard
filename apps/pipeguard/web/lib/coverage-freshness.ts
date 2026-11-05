export type CoverageSample = { at: string; observedMonotonic: number };

/** Cached health must age even when the local wall clock moves backwards. */
export function coverageSampleFresh(
  sample: CoverageSample | null,
  wallNow = Date.now(),
  monotonicNow = performance.now(),
): boolean {
  if (!sample) return false;
  const wallAge = wallNow - Date.parse(sample.at);
  const elapsed = monotonicNow - sample.observedMonotonic;
  return (
    Number.isFinite(wallAge) &&
    Number.isFinite(elapsed) &&
    wallAge >= 0 &&
    elapsed >= 0 &&
    wallAge <= 90000 &&
    elapsed <= 90000
  );
}
