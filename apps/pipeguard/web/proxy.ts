import { NextRequest, NextResponse } from "next/server";
import { localRequestAllowed } from "./lib/boundary";
export function proxy(request: NextRequest) {
  if (!localRequestAllowed(request.headers)) {
    return NextResponse.json(
      { error: "local_same_origin_required" },
      { status: 403 },
    );
  }
  return NextResponse.next();
}
export const config = { matcher: "/:path*" };
