import SceneSearch from "./components/SceneSearch";

export default function Home() {
  return (
    <>
      <header className="mx-auto w-full max-w-4xl px-4 pt-8 sm:px-6">
        <p className="font-display text-2xl text-ink">장면 기억 검색기</p>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-16 sm:px-6">
        <SceneSearch />
      </main>
      <footer className="mx-auto w-full max-w-4xl px-4 pb-8 text-sm text-muted sm:px-6">
        <p>영화 정보와 포스터는 TMDB에서 가져옵니다.</p>
        <p lang="en">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
      </footer>
    </>
  );
}
