import type { Metadata } from "next";
import Link from "next/link";

import EvalDashboard from "../components/EvalDashboard";

export const metadata: Metadata = {
  title: "평가 대시보드 · 장면 기억 검색기",
  description: "실험별 검색 정확도, 지연시간, 질의당 비용",
  robots: { index: false },
};

export default function EvalPage() {
  return (
    <>
      <header className="mx-auto flex w-full max-w-4xl items-baseline justify-between gap-4 px-4 pt-8 sm:px-6">
        <p className="font-display text-2xl text-ink">평가 대시보드</p>
        <Link href="/" className="text-sm text-muted underline-offset-4 hover:underline">
          검색으로 돌아가기
        </Link>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-16 sm:px-6">
        <EvalDashboard />
      </main>
    </>
  );
}
