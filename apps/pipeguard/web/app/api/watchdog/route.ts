import "server-only";
import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { resolve } from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { localRequestAllowed } from "@/lib/boundary";
import { parseWatchdog } from "@/lib/watchdog";

export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  if (!localRequestAllowed(request.headers))
    return NextResponse.json(
      { error: "local_same_origin_required" },
      { status: 403 },
    );
  let handle;
  try {
    // The launcher always runs Next from apps/pipeguard/web. No client path input.
    handle = await open(
      resolve(process.cwd(), "../../../data/local/watchdog/state.json"),
      constants.O_RDONLY | constants.O_NOFOLLOW,
    );
    const stat = await handle.stat();
    if (
      !stat.isFile() ||
      stat.size > 65536 ||
      (stat.mode & 0o077) !== 0 ||
      stat.uid !== process.getuid?.()
    )
      throw new Error("invalid_watchdog_state");
    const bytes = Buffer.alloc(65537);
    const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
    if (bytesRead > 65536) throw new Error("invalid_watchdog_state");
    const state = parseWatchdog(
      JSON.parse(bytes.subarray(0, bytesRead).toString("utf8")),
    );
    if (!state) throw new Error("invalid_watchdog_state");
    return NextResponse.json(state, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "watchdog_unavailable" },
      { status: 503 },
    );
  } finally {
    await handle?.close();
  }
}
