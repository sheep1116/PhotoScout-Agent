import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'PhotoScout · 去光发生的地方', description: '把摄影灵感，变成有据可循的拍摄计划。'};
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
