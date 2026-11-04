export async function boundedJSON(
  stream: ReadableStream<Uint8Array> | null,
  cap: number,
  timeoutMs = 5000,
) {
  if (!stream) throw new Error("missing_body");
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const deadline = performance.now() + timeoutMs;
  try {
    while (true) {
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error("body_timeout");
      let timer: ReturnType<typeof setTimeout> | undefined;
      let part: ReadableStreamReadResult<Uint8Array>;
      try {
        part = await Promise.race([
          reader.read(),
          new Promise<never>((_, reject) => {
            timer = setTimeout(
              () => reject(new Error("body_timeout")),
              remaining,
            );
          }),
        ]);
      } finally {
        clearTimeout(timer);
      }
      const { done, value } = part;
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
    // A broken source may never resolve cancellation; it must not defeat the deadline.
    void reader.cancel().catch(() => {});
  }
}
