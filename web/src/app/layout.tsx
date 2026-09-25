import type { Metadata, Viewport } from "next";
import { Instrument_Sans, Newsreader } from "next/font/google";

import { Providers } from "@/components/providers";
import "./globals.css";

// design-system.md §4.1: UI in Instrument Sans; Newsreader only when the assistant addresses you.
const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
  display: "swap",
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  display: "swap",
  axes: ["opsz"],
});

export const metadata: Metadata = {
  title: "MyPA",
  description: "Your personal assistant",
};

export const viewport: Viewport = {
  themeColor: "#fbfaf7", // --canvas; a meta tag can't read CSS variables
  viewportFit: "cover", // lets the bottom tab bar pad for env(safe-area-inset-bottom)
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${instrumentSans.variable} ${newsreader.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
