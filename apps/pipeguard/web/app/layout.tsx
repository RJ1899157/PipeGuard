import type { Metadata } from "next";
import { connection } from "next/server";
import "@xyflow/react/dist/style.css";
import "./globals.css";
export const metadata: Metadata = {
  title: "PipeGuard · Pipeline observability",
  description:
    "Local pipeline monitoring and evidence-preserving incident investigation",
  robots: { index: false, follow: false },
};
export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Nonces belong to this request, including error pages; never prerender HTML.
  await connection();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
