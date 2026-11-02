/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export default {
  reactStrictMode: true,
  poweredByHeader: false,
  // Django routes end in "/". Without this Next 308-redirects /api/x/ -> /api/x, and Django's
  // APPEND_SLASH redirects it straight back: an endless loop on every API call.
  skipTrailingSlashRedirect: true,
  // Week 5: an agent run may take up to its 60 s limit (plus a cold model start). The rewrite proxy's
  // default timeout is 30 s, which cut long runs off with an empty response, so allow 90 s.
  experimental: { proxyTimeout: 90_000 },
  // The browser only ever talks to this origin. Next forwards /api/* to Django, so the HttpOnly
  // auth cookies and the CSRF cookie are first-party and no CORS configuration is needed.
  async rewrites() {
    // The slash-terminated pattern comes first so the trailing "/" survives into the destination.
    return [
      { source: "/api/:path*/", destination: `${backend}/api/:path*/` },
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};
