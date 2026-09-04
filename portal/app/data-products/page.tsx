import Link from 'next/link';

import { CatalogEmptyState } from '@/components/catalog/CatalogEmptyState';
import { CompareTable } from '@/components/catalog/CompareTable';
import { FacetRail } from '@/components/catalog/FacetRail';
import { ProductCard } from '@/components/catalog/ProductCard';
import { ErrorState } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import type { CatalogPage, DiscoverResponse } from '@/lib/types';

export const dynamic = 'force-dynamic';

const FACET_KEYS = [
  'industry',
  'domain',
  'archetype',
  'certification',
  'sensitivity',
  'tier',
  'owner',
  'endpoint',
  'kpi',
  'quality_band',
] as const;

const SORTS = [
  { code: 'name', label: 'Name' },
  { code: 'quality', label: 'Quality' },
  { code: 'adoption', label: 'Adoption' },
  { code: 'recent', label: 'Recently updated' },
] as const;

type SearchParams = Record<string, string | string[] | undefined>;

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

export default async function DataProductsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const selected: Record<string, string[]> = {};
  for (const key of FACET_KEYS) {
    const values = asList(params[key]);
    if (values.length > 0) selected[key] = values;
  }
  const sort = typeof params.sort === 'string' ? params.sort : 'name';
  const cursor = typeof params.cursor === 'string' ? params.cursor : undefined;
  const compare = asList(params.compare);
  const query = typeof params.q === 'string' ? params.q : '';

  const result = await apiTry<CatalogPage>('/products', { ...selected, sort, cursor });

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <ErrorState
          title="The catalog could not be loaded"
          detail={result.problem.detail}
        />
      </div>
    );
  }

  const page = result.data;
  const comparing = page.items.filter((item) => compare.includes(item.product_id));

  if (page.items.length === 0) {
    const discovery = await apiTry<DiscoverResponse>('/discover', { q: query || 'data product' });
    const empty = discovery.ok ? discovery.data.empty_state : undefined;
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <CatalogEmptyState
          query={query || describeSelection(selected)}
          message={
            empty?.message ??
            'No product matches these filters. Widen them, or ask for what is missing.'
          }
          nearest={empty?.nearest ?? []}
          relatedDemand={empty?.related_demand ?? []}
          fileSupplyRequestUrl={
            empty?.file_supply_request_url ??
            `/requests/new/supply?query=${encodeURIComponent(query)}`
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
      <header className="mb-lg flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-primary">Data products</h1>
          <p className="mt-2xs text-sm text-secondary">
            {page.total} governed products. Every card shows quality, freshness, owner, adoption
            and the agents attached to it before you click anything.
          </p>
        </div>
        <nav aria-label="Sort" className="flex items-center gap-xs">
          <span className="text-2xs uppercase tracking-wide text-muted">Sort</span>
          {SORTS.map((option) => (
            <Link
              key={option.code}
              href={hrefWith(selected, { sort: option.code })}
              aria-current={sort === option.code ? 'true' : undefined}
              className={
                sort === option.code
                  ? 'rounded-md bg-sunken px-sm py-3xs text-xs font-medium text-primary'
                  : 'rounded-md px-sm py-3xs text-xs text-secondary hover:text-primary'
              }
            >
              {option.label}
            </Link>
          ))}
        </nav>
      </header>

      <div className="grid grid-cols-1 gap-xl lg:grid-cols-[240px_1fr]">
        <aside>
          <FacetRail facets={page.facets} selected={selected} basePath="/data-products" />
        </aside>

        <div>
          {comparing.length > 0 ? (
            <section className="mb-xl" aria-label="Comparison">
              <h2 className="mb-sm text-md font-semibold text-primary">Comparing</h2>
              <CompareTable products={comparing} />
            </section>
          ) : null}

          <ul
            role="list"
            className="grid grid-cols-1 gap-md sm:grid-cols-2 xl:grid-cols-3"
          >
            {page.items.map((product) => (
              <ProductCard key={product.product_id} product={product} />
            ))}
          </ul>

          {page.next_cursor ? (
            <div className="mt-xl flex justify-center">
              <Link
                href={hrefWith(selected, { sort, cursor: page.next_cursor })}
                className="rounded-md border border-strong px-lg py-sm text-sm font-medium text-primary"
              >
                Next page
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function hrefWith(
  selected: Record<string, string[]>,
  extra: Record<string, string | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, values] of Object.entries(selected)) {
    for (const value of values) params.append(key, value);
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined) params.set(key, value);
  }
  const query = params.toString();
  return query ? `/data-products?${query}` : '/data-products';
}

function describeSelection(selected: Record<string, string[]>): string {
  const parts = Object.entries(selected).flatMap(([key, values]) =>
    values.map((value) => `${key}: ${value}`),
  );
  return parts.length > 0 ? parts.join(', ') : 'these filters';
}
