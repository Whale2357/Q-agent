import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Q-Agent",
  description: "회의 맥락 판독 & 질문 큐레이션 엔진",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
