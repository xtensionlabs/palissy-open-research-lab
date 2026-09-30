import type { Metadata } from "next";
import { DM_Mono, Hanken_Grotesk, Newsreader } from "next/font/google";
import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-newsreader",
  axes: ["opsz"],
});
const hanken = Hanken_Grotesk({ subsets: ["latin"], variable: "--font-hanken" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-dm-mono" });

export const metadata: Metadata = {
  title: "Palissy",
  description: "An open research laboratory for biology. An AI collaborator that shows its working.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-scroll-behavior="smooth" className={`${newsreader.variable} ${hanken.variable} ${dmMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
