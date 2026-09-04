import Link from 'next/link';

import type { SearchResult } from '@/lib/types';

/**
 * The catalog empty state is never a dead end (BUILD.md section 12).
 *
 * It shows the nearest semantic matches, the demand already on the board, and a
 * new-supply request with the query carried into it — so a consumer who looked
 * for something the estate does not have leaves a signal rather than leaving.
 */
export function CatalogEmptyState({
  query,
  message,
  nearest,
  relatedDemand,
  fileSupplyRequestUrl,
}: {
  query: string;
  message: string;
  nearest: SearchResult[];
  relatedDemand: { demand_id: string; title: string; state: string; votes: number }[];
  fileSupplyRequestUrl: string;
}) {
  return (
    <section className="rounded-lg border border-subtle bg-raised p-xl">
      <h2 className="text-lg font-semibold text-primary">
        Nothing in the catalog matches “{query}” yet
      </h2>
      <p className="mt-xs max-w-2xl text-sm text-secondary">{message}</p>

      {nearest.length > 0 ? (
        <div className="mt-lg">
          <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
            Closest assets
          </h3>
          <ul className="mt-xs space-y-2xs">
            {nearest.map((result) => (
              <li key={`${result.asset_type}:${result.asset_id}`}>
                <Link
                  href={hrefFor(result)}
                  className="text-sm text-accent hover:underline"
                >
                  {result.name}
                </Link>
                <span className="ml-xs text-2xs uppercase tracking-wide text-muted">
                  {result.asset_type.replace(/_/g, ' ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {relatedDemand.length > 0 ? (
        <div className="mt-lg">
          <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
            Already on the demand board
          </h3>
          <ul className="mt-xs space-y-2xs">
            {relatedDemand.map((item) => (
              <li key={item.demand_id} className="text-sm text-secondary">
                <Link href={`/demand#${item.demand_id}`} className="text-accent hover:underline">
                  {item.title}
                </Link>
                <span className="ml-xs text-2xs text-muted">
                  {item.state.replace(/_/g, ' ')} · {item.votes} votes
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Link
        href={fileSupplyRequestUrl}
        className="mt-lg inline-block rounded-md bg-accent px-lg py-sm text-sm font-medium text-on-hero"
      >
        Ask for this data product
      </Link>
    </section>
  );
}

function hrefFor(result: SearchResult): string {
  switch (result.asset_type) {
    case 'data_product':
      return `/data-products/${result.asset_id}`;
    case 'agent':
      return `/agents/${result.asset_id}`;
    case 'kpi':
      return `/kpis/${result.asset_id}`;
    default:
      return `/discover?q=${encodeURIComponent(result.name)}`;
  }
}
