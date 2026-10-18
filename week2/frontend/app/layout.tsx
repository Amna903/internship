import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HealthProfile",
  description: "Wellness profile builder (demo with synthetic data only).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
