import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HR Absensi — Panel Kontrol",
  description: "Sistem pengelolaan aturan bisnis absensi & payroll",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="antialiased">{children}</body>
    </html>
  );
}
