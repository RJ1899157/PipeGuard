"use client";
import { useEffect, useState } from "react";

type Expiring = { expires_at: string; expired?: boolean };

/** Invalid dates fail closed; a captured server flag never extends an expiry. */
export function proposalExpired(row: Expiring, now: number): boolean {
  const expiry = Date.parse(row.expires_at);
  return row.expired === true || !Number.isFinite(expiry) || expiry <= now;
}

/** Wake only at the next visible expiry, instead of polling every proposal. */
export function useExpiry(rows: readonly Expiring[] | undefined): number {
  const [tick, setTick] = useState(0);
  const now = Date.now();
  useEffect(() => {
    const next = Math.min(
      ...(rows || [])
        .map((row) => Date.parse(row.expires_at))
        .filter((time) => time > now),
    );
    if (!Number.isFinite(next)) return;
    const timer = setTimeout(
      () => setTick((value) => value + 1),
      Math.min(next - now + 50, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [rows, now, tick]);
  return now;
}
