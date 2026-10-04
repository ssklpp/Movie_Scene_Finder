import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // 영화 포스터(TMDB)
    remotePatterns: [new URL("https://image.tmdb.org/t/p/**")],
  },
};

export default nextConfig;
