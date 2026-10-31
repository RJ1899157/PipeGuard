"use client";
import { useEffect, useState } from "react";
import { useRead } from "@/lib/use-read";
import { watchdogFresh, type WatchdogState } from "@/lib/watchdog";

export function WatchdogStatus({
  demo,
  revision,
}: {
  demo: boolean;
  revision: number;
}) {
  const [poll, setPoll] = useState(0);
  const result = useRead<WatchdogState>("watchdog", {}, demo, revision + poll);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
      setPoll((n) => n + 1);
    }, 15000);
    return () => clearInterval(timer);
  }, []);
  const fresh = result.data && watchdogFresh(result.data, now);
  return (
    <section className="notice" aria-label="Independent service watcher">
      <div>
        <strong>Independent service watcher</strong>
        <p>
          {result.loading
            ? "Loading watcher status…"
            : result.error || !result.data
              ? "Watcher status unavailable. Start the independent watcher; service health is unknown."
              : !fresh
                ? "The latest watcher sample is stale or its clock is inconsistent. Current service health is unknown."
                : `API: ${result.data.status.api} · Database: ${result.data.status.database} · Monitor: ${result.data.status.monitor}`}
        </p>
        {result.data && (
          <small>
            Checked {new Date(result.data.checked_at).toISOString()} · Watcher
            status refreshes every 15 seconds.
          </small>
        )}
        <p>
          This watcher runs separately on this Mac. Total power or internet loss
          requires a watcher on another device.
        </p>
      </div>
    </section>
  );
}
