import Link from 'next/link';

import type { IndustryTile } from '@/lib/types';
import { count } from '@/lib/units';

/**
 * The industry selector (band 3, M11.6).
 *
 * Selecting a tile re-renders bands 4 to 6 for that vertical. It is the
 * demo-persona switch: a client walkthrough tailored in one click, which is why
 * it sits above the bands it changes rather than inside any of them.
 *
 * Tiles are links carrying a query parameter, not client state. A walkthrough
 * you can send someone as a URL is worth more than one that only exists in a
 * browser tab, and it means the tailored page renders on the server with
 * nothing arriving late.
 *
 * Each tile carries its counts, so a visitor can see how much is behind a
 * vertical before choosing it. A tile with nothing behind it is never offered —
 * the API does not return one.
 */
export function IndustrySelector({
  industries,
  selected,
}: {
  industries: IndustryTile[];
  selected: string | null;
}) {
  if (industries.length === 0) return null;

  return (
    <section className="industries" aria-labelledby="industries-heading">
      <h2 id="industries-heading" className="band-heading">
        Show me an industry
      </h2>
      <p className="band-sub">
        The bands below re-render for the vertical you pick. It is the same ranking,
        narrowed — not a different one arranged for the occasion.
      </p>
      <ul className="industry-strip" role="list">
        <li>
          <Link
            href="/"
            scroll={false}
            className="industry-tile"
            aria-current={selected === null ? 'true' : undefined}
          >
            <span className="industry-label">Everything</span>
            <span className="industry-counts">the whole estate</span>
          </Link>
        </li>
        {industries.map((industry) => (
          <li key={industry.code}>
            <Link
              href={`/?industry=${encodeURIComponent(industry.code)}`}
              scroll={false}
              className="industry-tile"
              aria-current={selected === industry.code ? 'true' : undefined}
            >
              <span className="industry-label">{industry.label}</span>
              <span className="industry-counts tabular-nums">
                {count(industry.products, 'product', 'products')} ·{' '}
                {count(industry.agents, 'agent', 'agents')}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
