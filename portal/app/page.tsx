import { ActivityTicker } from '@/components/landing/ActivityTicker';
import { AgentCarousel } from '@/components/landing/AgentCarousel';
import { AnswerTheatre } from '@/components/landing/AnswerTheatre';
import { Constellation } from '@/components/landing/Constellation';
import { Counters } from '@/components/landing/Counters';
import { Hero } from '@/components/landing/Hero';
import { HowItWorks } from '@/components/landing/HowItWorks';
import { IndustrySelector } from '@/components/landing/IndustrySelector';
import { ProductRibbon } from '@/components/landing/ProductRibbon';
import { ValueProof } from '@/components/landing/ValueProof';
import Link from 'next/link';

import { apiTry } from '@/lib/api';
import type {
  CountersBand,
  FeaturedBand,
  HeroBand,
  IndustryTile,
  ProofBand,
  TheatreBand,
} from '@/lib/types';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * The landing page: ten bands, every one of them reading the platform.
 *
 * Two rules shape the whole file. **Nothing renders a skeleton** — a marketing
 * surface that shows grey boxes while it thinks has told a first-time visitor
 * that the product is slow. A band whose data is unavailable collapses instead,
 * and the page is still coherent without it. And **every band reserves its box
 * before paint**: the hero, the ribbon and the theatre are all fixed-aspect, so
 * the layout does not move once. That is what a CLS budget of 0.00 means in
 * practice, and it is the reason each band is fetched here on the server rather
 * than arriving later.
 *
 * The industry parameter re-renders bands 4 to 6 for one vertical (M11.6). It
 * is a query parameter rather than client state, so a tailored walkthrough is a
 * URL somebody can send.
 */
export default async function LandingPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const industry = typeof params.industry === 'string' ? params.industry : null;

  const [hero, featured, industries, counters, theatre, proof] = await Promise.all([
    apiTry<HeroBand>('/landing/hero'),
    apiTry<FeaturedBand>('/landing/featured', { industry: industry ?? undefined }),
    apiTry<{ industries: IndustryTile[] }>('/landing/industries'),
    apiTry<CountersBand>('/landing/counters'),
    apiTry<TheatreBand>('/landing/theatre'),
    apiTry<ProofBand>('/landing/proof'),
  ]);

  const products = featured.ok ? featured.data.products : [];
  const agents = featured.ok ? featured.data.agents : [];
  const staticCards = featured.ok ? featured.data.limits.static_grid_cards : 0;
  const totalProducts =
    counters.ok
      ? (counters.data.counters.find((counter) => counter.code === 'products')?.value ?? 0)
      : 0;

  return (
    <div className="landing">
      {hero.ok ? (
        <Hero hero={hero.data} searchExamples={products.map((product) => product.name)} />
      ) : (
        <StaticHero />
      )}

      {counters.ok ? <Counters counters={counters.data.counters} /> : null}

      <div className="landing-bands">
        {industries.ok ? (
          <IndustrySelector industries={industries.data.industries} selected={industry} />
        ) : null}

        <ProductRibbon
          products={products}
          staticCards={staticCards}
          totalProducts={totalProducts}
        />

        <AgentCarousel agents={agents} />

        {theatre.ok ? <AnswerTheatre traces={theatre.data.traces} /> : null}

        <HowItWorks />

        {hero.ok ? (
          <section className="mesh-band" aria-labelledby="mesh-band-heading">
            <h2 id="mesh-band-heading" className="band-heading">
              How it all connects
            </h2>
            <p className="band-sub">
              The same graph as the hero, at full strength and interactive. Hover a
              product to see what shares its sources.
            </p>
            <Constellation hero={hero.data} pulses={[]} interactive />
            <Link href="/mesh/data" className="mesh-band-link">
              Open the mesh explorer
            </Link>
          </section>
        ) : null}

        {proof.ok ? <ValueProof tiles={proof.data.tiles} /> : null}

        {counters.ok ? (
          <ActivityTicker events={counters.data.ticker} live />
        ) : (
          // 13.5: a dead channel hides the band. A frozen stale ticker claims a
          // liveness it does not have.
          <ActivityTicker events={[]} live={false} />
        )}
      </div>
    </div>
  );
}

/**
 * The hero without its graph.
 *
 * If the constellation is unavailable the copy still stands on its own, in the
 * same box, at the same size. No skeleton, no shifted layout, and no apology —
 * a visitor who never sees the graph has lost nothing they were promised.
 */
function StaticHero() {
  return (
    <section className="hero">
      <div className="hero-scrim" aria-hidden />
      <div className="hero-copy">
        <h1 className="hero-headline">
          Every governed data product and AI agent in the enterprise. One shelf.
        </h1>
        <p className="hero-sub">
          Find it, watch it answer, request it, use it today — with the contract, the
          quality score, the entitlement and the value case attached to each one.
        </p>
        <div className="hero-actions">
          <Link href="/data-products" className="hero-cta-primary">
            Browse the catalog
          </Link>
          <Link href="/agents" className="hero-cta-ghost">
            Browse the agents
          </Link>
        </div>
      </div>
    </section>
  );
}
