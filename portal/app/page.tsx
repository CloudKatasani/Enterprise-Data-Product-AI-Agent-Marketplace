import Link from 'next/link';

import { getThemeConfig } from '@/lib/theme/product';

/**
 * Landing page. The moving surfaces specified in BUILD.md section 13 are built
 * in M11 on top of the motion controller; until then this renders the static
 * equivalent that reduced-motion users will always see, so the page is never a
 * placeholder and never a skeleton (13.2).
 */
export default function LandingPage() {
  const { productName } = getThemeConfig();

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-3xl">
      <section className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-primary">
          Data products and the agents that run on them, in one governed catalog.
        </h1>
        <p className="mt-md text-md text-secondary">
          {productName} catalogues, governs, observes and demonstrates every data product and
          AI agent as a single supply chain — with quality, contracts, entitlements and a
          quantified value case attached to each one.
        </p>
        <div className="mt-lg flex flex-wrap gap-sm">
          <Link
            href="/data-products"
            className="rounded-md bg-accent px-lg py-sm text-sm font-medium text-on-hero"
          >
            Browse data products
          </Link>
          <Link
            href="/agents"
            className="rounded-md border border-strong px-lg py-sm text-sm font-medium text-primary"
          >
            Browse agents
          </Link>
        </div>
      </section>
    </div>
  );
}
