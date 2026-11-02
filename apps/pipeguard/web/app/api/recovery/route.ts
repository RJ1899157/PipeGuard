import "server-only";
import { NextRequest, NextResponse } from "next/server";
import { localRequestAllowed } from "@/lib/boundary";
import { boundedJSON } from "@/lib/bounded-json";
import { recoveryMutation, recoveryRead } from "@/lib/recovery-boundary";

export const dynamic = "force-dynamic";
async function broker(request: NextRequest, mutate: boolean) {
  if (
    !localRequestAllowed(request.headers) ||
    (mutate &&
      (request.headers.get("origin") !==
        `http://${request.headers.get("host")}` ||
        request.headers.get("sec-fetch-site") !== "same-origin" ||
        request.headers.get("content-type")?.split(";")[0].trim() !==
          "application/json"))
  )
    return NextResponse.json(
      { error: "local_same_origin_required" },
      { status: 403 },
    );
  let path: string | null = null,
    body: string | undefined;
  try {
    if (mutate) {
      const target = recoveryMutation(await boundedJSON(request.body, 2048));
      path = target?.path || null;
      body = target?.body;
    } else
      path = recoveryRead(
        request.nextUrl.searchParams.get("id") || "",
        request.nextUrl.searchParams.get("before"),
      );
  } catch {
    /* Invalid or oversized bodies fail before reaching the API. */
  }
  if (!path)
    return NextResponse.json(
      { error: "invalid_recovery_request" },
      { status: 400 },
    );
  const token = process.env.PIPEGUARD_ADMIN_TOKEN;
  if (!token)
    return NextResponse.json(
      { error: "dashboard_not_configured" },
      { status: 503 },
    );
  try {
    const upstream = await fetch(`http://127.0.0.1:8000${path}`, {
      method: mutate ? "POST" : "GET",
      body,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(mutate ? 60000 : 12000),
    });
    return NextResponse.json(await boundedJSON(upstream.body, 1024 * 1024), {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "recovery_connection_unknown" },
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
