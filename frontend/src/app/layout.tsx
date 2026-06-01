import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "On1y Knowledge",
  description: "Tag-first RSS and AI knowledge workspace"
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
