import type { Metadata } from "next";

import { AppearanceProvider } from "@/components/appearance-provider";
import { TauriExternalLinks } from "@/components/tauri-external-links";

import "./globals.css";

export const metadata: Metadata = {
  title: "On1y Knowledge",
  description: "Tag-first RSS and AI knowledge workspace",
  icons: { icon: "/on1y-logo.png", apple: "/on1y-logo.png" }
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AppearanceProvider />
        <TauriExternalLinks />
        {children}
      </body>
    </html>
  );
}
