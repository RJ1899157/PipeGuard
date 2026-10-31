import "server-only";
import { NextRequest, NextResponse } from "next/server";
import { localRequestAllowed, readPath } from "@/lib/boundary";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  if (!localRequestAllowed(request.headers))
    return NextResponse.json(
      { error: "local_same_origin_required" },
      { status: 403 },
    );
  const path = readPath(request.nextUrl.searchParams);
  if (!path)
    return NextResponse.json(
      { error: "invalid_read_request" },
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
      method: "GET",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(12000),
    });
    if (!upstream.ok)
      return NextResponse.json(
        {
          error:
            upstream.status === 401 || upstream.status === 403
              ? "dashboard_unauthorized"
              : upstream.status === 404
                ? "record_not_found"
                : "api_unavailable",
        },
        {
          status:
            upstream.status === 404
              ? 404
              : upstream.status === 401 || upstream.status === 403
                ? 502
                : 503,
        },
      );
    const data = await upstream.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "api_unavailable" }, { status: 503 });
  }
}
