import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { SiteFooter } from '@/components/shell/SiteFooter';
import { SiteHeader } from '@/components/shell/SiteHeader';
import { getThemeConfig } from '@/lib/theme/product';
import '@/styles/globals.css';

export function generateMetadata(): Metadata {
  const { productName } = getThemeConfig();
  return {
    title: {
      default: productName,
      template: `%s — ${productName}`,
    },
    description:
      'Governed catalog of data products and the AI agents that run on them: quality, ' +
      'contracts, entitlements, demos and value in one supply chain.',
  };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const { productName } = getThemeConfig();

  return (
    <html lang="en" dir="ltr">
      <body>
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <SiteHeader productName={productName} />
        <main id="main">{children}</main>
        <SiteFooter productName={productName} />
      </body>
    </html>
  );
}
