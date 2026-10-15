import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { SiteFooter } from '@/components/shell/SiteFooter';
import { SiteHeader } from '@/components/shell/SiteHeader';
import { getLocale } from '@/lib/locale';
import { getThemeConfig } from '@/lib/theme/product';
import '@/styles/globals.css';

// Configuration is read from the process environment at request time, so no
// page may be prerendered at build time — including Next's built-in
// /_not-found, which inherits only this layout. A container image is then
// built once, with no configuration, and configured where it runs.
export const dynamic = 'force-dynamic';

export function generateMetadata(): Metadata {
  const { productName } = getThemeConfig();
  return {
    title: {
      default: productName,
      template: `%s — ${productName}`,
    },
    description:
      'Every governed data product and AI agent in the enterprise — on one shelf.',
  };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const { productName } = getThemeConfig();
  // Direction is a property of the document, set once. Every style in this
  // portal is written in logical properties, so mirroring the whole interface
  // for a right-to-left locale is this attribute and nothing else (M12.4).
  const { locale, direction } = getLocale();

  return (
    <html lang={locale} dir={direction}>
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
