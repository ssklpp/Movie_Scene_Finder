import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 이미지(frontend/Dockerfile)만 standalone으로 빌드한다. Vercel 배포는 그대로.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  images: {
    // 영화 포스터(TMDB)
    remotePatterns: [new URL("https://image.tmdb.org/t/p/**")],
  },
};

export default nextConfig;
