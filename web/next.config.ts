import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The browser only ever talks to this origin; /api/* is proxied to the backend. Production does
  // the same thing in the reverse proxy (decisions-log 2026-08-28), so client code is identical.
  rewrites: async () => [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }],
};

export default nextConfig;
