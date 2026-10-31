"use client";
import { useEffect, useState } from "react";
import { demoRead } from "./demo";
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
  const key =
    params === null
      ? null
      : new URLSearchParams({
          kind,
          ...params,
          ...(scenario ? { scenario } : {}),
        }).toString();
  const identity = `${demo}:${revision}:${key}`;
  const [state, setState] = useState<{
    data: T | null;
    error: string | null;
    loading: boolean;
    at: string | null;
    key: string | null;
  }>({ data: null, error: null, loading: false, at: null, key: null });
  useEffect(() => {
    if (key === null) {
      setState({
        data: null,
        error: null,
        loading: false,
        at: null,
        key: identity,
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
    });
    async function load() {
      try {
        let data: unknown;
        if (demo) data = demoRead(kind, new URLSearchParams(key!));
        else {
          const response = await fetch(`/api/read?${key}`, {
            cache: "no-store",
            signal: controller.signal,
          });
          if (!response.ok) {
            const body = await response.json();
            throw new Error(body.error || "api_unavailable");
          }
          data = await response.json();
        }
        if (!controller.signal.aborted)
          setState({
            data: data as T,
            error: null,
            loading: false,
            at: new Date().toISOString(),
            key: identity,
          });
      } catch (error) {
        if (!controller.signal.aborted)
          setState({
            data: null,
            error: error instanceof Error ? error.message : "api_unavailable",
            loading: false,
            at: null,
            key: identity,
          });
      }
    }
    void load();
    return () => controller.abort();
  }, [key, demo, revision, kind, identity]);
  return state.key === identity
    ? state
    : { data: null, error: null, loading: key !== null, at: null, key };
}
