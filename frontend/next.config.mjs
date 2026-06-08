/** @type {import('next').NextConfig} */
const backend =
  process.env.NEXT_PUBLIC_ON1Y_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8765";

const nextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  /** Dev only: proxy /api/* to on1y serve so `npm run dev` works without env vars. */
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  }
};

export default nextConfig;
