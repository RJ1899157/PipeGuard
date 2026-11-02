import "server-only";
import { NextRequest, NextResponse } from "next/server";
import { localRequestAllowed } from "@/lib/boundary";

export const dynamic = "force-dynamic";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function boundedJSON(
  stream: ReadableStream<Uint8Array> | null,
  cap: number,
) {
  if (!stream) throw new Error("missing_body");
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > cap) throw new Error("body_limit");
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } finally {
    await reader.cancel().catch(() => {});
  }
}
async function broker(request: NextRequest, submit: boolean) {
  if (!localRequestAllowed(request.headers))
    return NextResponse.json(
      { error: "local_same_origin_required" },
      { status: 403 },
    );
  let id: string, body: string | undefined;
  const before = request.nextUrl.searchParams.get("before");
  if (submit) {
    const origin = `http://${request.headers.get("host")}`;
    if (
      request.headers.get("origin") !== origin ||
      request.headers.get("sec-fetch-site") !== "same-origin" ||
      request.headers.get("content-type")?.split(";")[0].trim() !==
        "application/json"
    )
      return NextResponse.json(
        { error: "local_same_origin_required" },
        { status: 403 },
      );
    try {
      const value = await boundedJSON(request.body, 1024);
      if (
        !value ||
        Object.keys(value).sort().join(",") !==
          "free_plan_confirmed,incident_id,request_key" ||
        typeof value.incident_id !== "string" ||
        !uuid.test(value.incident_id) ||
        typeof value.request_key !== "string" ||
        !uuid.test(value.request_key) ||
        value.free_plan_confirmed !== true
      )
        throw new Error("invalid_body");
      id = value.incident_id;
      body = JSON.stringify({
        request_key: value.request_key,
        free_plan_confirmed: true,
      });
    } catch {
      return NextResponse.json(
        { error: "invalid_investigation_request" },
        { status: 400 },
      );
    }
  } else {
    id = request.nextUrl.searchParams.get("id") || "";
    if (!uuid.test(id) || (before !== null && !uuid.test(before)))
      return NextResponse.json(
        { error: "invalid_investigation_request" },
        { status: 400 },
      );
  }
  const token = process.env.PIPEGUARD_ADMIN_TOKEN;
  if (!token)
    return NextResponse.json(
      { error: "dashboard_not_configured" },
      { status: 503 },
    );
  try {
    const suffix = submit
      ? ""
      : `?limit=20${before ? `&before=${encodeURIComponent(before)}` : ""}`;
    const upstream = await fetch(
      `http://127.0.0.1:8000/v1/incidents/${id}/investigations${suffix}`,
      {
        method: submit ? "POST" : "GET",
        body,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(submit ? 95000 : 12000),
      },
    );
    const data = await boundedJSON(upstream.body, 2 * 1024 * 1024);
    return NextResponse.json(data, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "investigation_connection_unknown" },
      { status: 503 },
    );
  }
}
export async function GET(request: NextRequest) {
  return broker(request, false);
}
export async function POST(request: NextRequest) {
  return broker(request, true);
}
