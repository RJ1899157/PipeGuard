import { NextRequest, NextResponse } from "next/server";
import {
  localRequestAllowed,
  localRequestRejection,
  localDocumentAllowed,
} from "./lib/boundary";
import { requestSecurity } from "./lib/security";
export function proxy(request: NextRequest) {
  if (
    !localRequestAllowed(request.headers) &&
    !localDocumentAllowed(
      request.headers,
      request.method,
      request.nextUrl.pathname,
    )
  ) {
    return NextResponse.json(
      {
        error: "local_same_origin_required",
        reason: localRequestRejection(request.headers),
      },
      { status: 403 },
    );
  }
  const { requestHeaders, policy } = requestSecurity(
    request.headers,
    process.env.NODE_ENV === "development",
  );
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Cache-Control", "no-store");
  return response;
}
export const config = { matcher: "/:path*" };
