import type { Metadata } from "next";
import { IBM_Plex_Sans_KR, Song_Myung } from "next/font/google";
import "./globals.css";

// 한글 글꼴은 글자 수가 많아 미리 불러오지 않고, 필요한 글자 범위만 내려받게 둔다.
// (Song Myung은 라틴 subset이 없어 preload 옵션 자체가 없다.)
const songMyung = Song_Myung({
  weight: "400",
  variable: "--font-song-myung",
  display: "swap",
});

const plexKr = IBM_Plex_Sans_KR({
  weight: ["400", "500", "600"],
  variable: "--font-plex-kr",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "장면 기억 검색기",
  description: "기억나는 영화 장면을 적거나 사진을 올리면 어떤 영화인지 찾아 줍니다.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${songMyung.variable} ${plexKr.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
