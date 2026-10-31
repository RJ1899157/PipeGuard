"use client";
import { useEffect, useRef, useState } from "react";
import { demoRead } from "./demo";
import { snapshotKinds } from "./boundary";
import type { ReadSnapshot } from "./types";
export function useRead<T>(
  kind: string,
  params: Record<string, string> | null,
  demo: boolean,
  revision: number,
) {
  const scenario =
    demo && typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("state") || ""
      : "";
  const fixtures: Record<string, string> =
    demo && typeof window !== "undefined"
      ? {
          graph_fixture:
            new URLSearchParams(window.location.search).get("graph") || "",
          quality_fixture:
            new URLSearchParams(window.location.search).get("quality") || "",
        }
      : {};
  const key =
    params === null
      ? null
      : new URLSearchParams({
          kind,
          ...params,
          ...fixtures,
          ...(scenario ? { scenario } : {}),
        }).toString();
  const identity = `${demo}:${revision}:${key}`;
  const scopeQuery = new URLSearchParams(key || "");
  scopeQuery.delete("offset");
  const snapshotScope = `${demo}:${revision}:${scopeQuery}`;
  const snapshotRef = useRef<{ scope: string; token: string } | null>(null);
  const [state, setState] = useState<{
    data: T | null;
    error: string | null;
    loading: boolean;
    at: string | null;
    key: string | null;
    page: { has_more: boolean; snapshot: ReadSnapshot } | null;
  }>({
    data: null,
    error: null,
    loading: false,
    at: null,
    key: null,
    page: null,
  });
  useEffect(() => {
    if (key === null) {
      setState({
        data: null,
        error: null,
        loading: false,
        at: null,
        key: identity,
        page: null,
      });
      return;
    }
    const controller = new AbortController();
    setState({
      data: null,
      error: null,
      loading: true,
      at: null,
      key: identity,
      page: null,
    });
    async function load() {
      try {
        let data: unknown;
        let page: { has_more: boolean; snapshot: ReadSnapshot } | null = null;
        if (demo) data = demoRead(kind, new URLSearchParams(key!));
        else {
          const query = new URLSearchParams(key!);
          const paged = snapshotKinds.includes(kind);
          if (paged)
            query.set(
              "snapshot",
              snapshotRef.current?.scope === snapshotScope
                ? snapshotRef.current.token
                : "new",
            );
          const response = await fetch(
            kind === "watchdog" ? "/api/watchdog" : `/api/read?${query}`,
            {
              cache: "no-store",
              signal: controller.signal,
            },
          );
          if (!response.ok) {
            const body = await response.json();
            throw new Error(body.error || "api_unavailable");
          }
          data = await response.json();
          if (paged) {
            const envelope = data as {
              items: unknown[];
              has_more: boolean;
              snapshot: ReadSnapshot;
            };
            if (!Array.isArray(envelope.items) || !envelope.snapshot?.token)
              throw new Error("invalid_read_snapshot");
            page = { has_more: envelope.has_more, snapshot: envelope.snapshot };
            if (!controller.signal.aborted)
              snapshotRef.current = {
                scope: snapshotScope,
                token: envelope.snapshot.token,
              };
            if (kind === "incidents" || kind === "history")
              data = envelope.items;
          }
        }
        if (!controller.signal.aborted)
          setState({
            data: data as T,
            error: null,
            loading: false,
            at: new Date().toISOString(),
            key: identity,
            page,
          });
      } catch (error) {
        if (!controller.signal.aborted)
          setState({
            data: null,
            error: error instanceof Error ? error.message : "api_unavailable",
            loading: false,
            at: null,
            key: identity,
            page: null,
          });
      }
    }
    void load();
    return () => controller.abort();
  }, [key, demo, revision, kind, identity, snapshotScope]);
  return state.key === identity
    ? state
    : {
        data: null,
        error: null,
        loading: key !== null,
        at: null,
        key,
        page: null,
      };
}
