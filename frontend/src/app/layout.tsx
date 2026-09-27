import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'ATELIER / Virtual Try-On', description: 'Your wardrobe, reimagined. An image-first virtual fitting studio.' };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
