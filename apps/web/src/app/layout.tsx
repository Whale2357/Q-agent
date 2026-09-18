import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "프랑켄슈타인 — 회의를 바꾸는 단 하나의 질문",
  description: "회의 맥락을 읽고 가치 있는 질문만 평가·선별하는 질문 큐레이션 엔진",
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
