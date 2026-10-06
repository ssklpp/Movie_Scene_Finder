# frontend

Movie Scene Finder의 웹 화면입니다(Next.js 16, TypeScript, Tailwind). 프로젝트 전체 설명은 [루트 README](../README.md)에 있습니다.

- `/`: 검색 화면(장면 묘사 또는 사진 → 진행 단계 → 재질문 → 결과)
- `/eval`: 내부 평가 대시보드(backend `GET /eval/runs`)

## 실행

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL = backend 주소(로컬은 http://localhost:8000)
pnpm install
pnpm dev                     # http://localhost:3000
pnpm lint && pnpm test       # ESLint, Vitest
```

저장소 루트에서 `make dev`를 실행하면 backend와 함께 뜹니다.

## 구조

- `app/components/SceneSearch.tsx`: 검색 상태(검색 → 진행 단계 → 재질문 → 결과) 관리
- `app/lib/api.ts`: POST SSE 응답을 `fetch` 스트림으로 읽음(`EventSource`는 GET만 지원)
- `app/components/EvalDashboard.tsx`: `/eval` 막대 차트와 지표 표
- `app/globals.css`: 디자인 토큰(`@theme`)

배포는 Vercel(Root Directory `frontend`, 환경 변수 `NEXT_PUBLIC_API_URL`)입니다.
