# 프런트엔드 이미지(Next.js standalone). 빌드 컨텍스트는 frontend/.
#   docker build -t msf-frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 frontend
# NEXT_PUBLIC_ 변수는 빌드할 때 번들에 박히므로 실행 시가 아니라 빌드 인자로 넘긴다.
# 배포(Vercel)는 이 파일을 쓰지 않는다.

FROM node:22-slim AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# standalone은 public과 .next/static을 복사하지 않으므로 따로 넣는다(Next.js output 문서)
FROM node:22-slim
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
