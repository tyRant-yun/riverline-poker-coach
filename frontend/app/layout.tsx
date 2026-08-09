import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Riverline Poker Coach",
  description: "可追溯证据驱动的 HU NLHE 策略教练",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
