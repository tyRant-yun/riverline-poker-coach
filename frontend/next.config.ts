import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The app is a single client-side page; static export keeps the deployed
  // frontend as plain files behind nginx (which proxies /v1/* to the API).
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
