import { randomBytes } from "node:crypto";

/** Override client-supplied nonce/CSP headers before Next renders the document. */
export function requestSecurity(headers: Headers, development: boolean) {
  const nonce = randomBytes(32).toString("base64");
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    "script-src-attr 'none'",
    // React Flow positions and ECharts sizes elements with dynamic inline styles.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
  const requestHeaders = new Headers(headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  return { requestHeaders, policy };
}
