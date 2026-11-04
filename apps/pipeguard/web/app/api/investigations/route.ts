import "server-only";
import { NextRequest, NextResponse } from "next/server";
import { boundedJSON } from "@/lib/bounded-json";
import { localRequestAllowed } from "@/lib/boundary";
import {
  investigationId,
  investigationSubmission,
} from "@/lib/investigation-boundary";

export const dynamic = "force-dynamic";
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
      const target = investigationSubmission(
        await boundedJSON(request.body, 1024),
      );
      if (!target) throw new Error("invalid_body");
      id = target.id;
      body = target.body;
    } catch {
      return NextResponse.json(
        { error: "invalid_investigation_request" },
        { status: 400 },
      );
    }
  } else {
    id = request.nextUrl.searchParams.get("id") || "";
    if (!investigationId(id) || (before !== null && !investigationId(before)))
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
