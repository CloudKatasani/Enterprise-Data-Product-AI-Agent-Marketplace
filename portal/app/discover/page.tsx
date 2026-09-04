import Link from 'next/link';

import { CatalogEmptyState } from '@/components/catalog/CatalogEmptyState';
import { ErrorState } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import type { DiscoverResponse, SearchResult } from '@/lib/types';

export const dynamic = 'force-dynamic';

const ASSET_LABEL: Record<string, string> = {
  data_product: 'Data product',
  agent: 'Agent',
  kpi: 'KPI',
  glossary_term: 'Glossary term',
};

export default async function DiscoverPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query = typeof params.q === 'string' ? params.q.trim() : '';

  return (
    <div className="mx-auto max-w-screen-xl px-lg py-2xl">
      <h1 className="text-2xl font-semibold tracking-tight text-primary">Discover</h1>
      <p className="mt-2xs max-w-2xl text-sm text-secondary">
        One search across data products, agents and the certified KPI register. Results are
        ranked by a rubric, and every result explains why it ranked where it did.
      </p>

      <form action="/discover" method="get" role="search" className="mt-lg flex max-w-2xl gap-sm">
        <label htmlFor="q" className="sr-only">
          Search the catalog
        </label>
        <input
          id="q"
          name="q"
          type="search"
          defaultValue={query}
          placeholder="Ask in your own words, or type an exact name"
          className="flex-1 rounded-md border border-strong bg-raised px-md py-sm text-sm text-primary"
        />
        <button
          type="submit"
          className="rounded-md bg-accent px-lg py-sm text-sm font-medium text-on-hero"
        >
          Search
        </button>
      </form>

      {query ? <Results query={query} /> : <Prompt />}
    </div>
  );
}

function Prompt() {
  return (
    <p className="mt-xl rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
      Search for an asset by name, by the question you are trying to answer, or by the KPI you
      need. Exact names always win over near matches.
    </p>
  );
}

async function Results({ query }: { query: string }) {
  const result = await apiTry<DiscoverResponse>('/discover', { q: query });

  if (!result.ok) {
    return (
      <div className="mt-xl">
        <ErrorState title="Search is unavailable" detail={result.problem.detail} />
      </div>
    );
  }

  const response = result.data;

  if (response.results.length === 0) {
    const empty = response.empty_state;
    return (
      <div className="mt-xl">
        <CatalogEmptyState
          query={query}
          message={empty?.message ?? 'Nothing matched that query.'}
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
    <section className="mt-xl" aria-label="Search results">
      <p className="text-xs text-muted">
        {response.results.length} results, ranked under rubric{' '}
        <code className="font-mono">{response.rubric_version_id}</code>
      </p>
      <ul role="list" className="mt-md space-y-sm">
        {response.results.map((item) => (
          <ResultRow key={`${item.asset_type}:${item.asset_id}`} result={item} />
        ))}
      </ul>
    </section>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  return (
    <li className="rounded-lg border border-subtle bg-raised p-md">
      <div className="flex flex-wrap items-baseline justify-between gap-sm">
        <h2 className="text-md font-semibold text-primary">
          <Link href={hrefFor(result)} className="hover:underline">
            {result.name}
          </Link>
        </h2>
        <span className="text-2xs uppercase tracking-wide text-muted">
          {ASSET_LABEL[result.asset_type] ?? result.asset_type}
        </span>
      </div>
      <p className="mt-3xs font-mono text-xs text-muted">{result.asset_id}</p>
      <details className="mt-xs">
        <summary className="cursor-pointer text-xs text-secondary">Why this ranked here</summary>
        <dl className="mt-2xs grid grid-cols-2 gap-x-lg gap-y-3xs text-xs sm:grid-cols-3">
          <div>
            <dt className="text-muted">Exact name match</dt>
            <dd className="text-secondary">{result.explanation.exact_name_match ? 'yes' : 'no'}</dd>
          </div>
          <div>
            <dt className="text-muted">Lexical rank</dt>
            <dd className="text-secondary">{result.explanation.lexical_rank ?? 'not retrieved'}</dd>
          </div>
          <div>
            <dt className="text-muted">Semantic rank</dt>
            <dd className="text-secondary">
              {result.explanation.semantic_rank ?? 'not retrieved'}
            </dd>
          </div>
          {Object.entries(result.explanation.signals).map(([signal, value]) => (
            <div key={signal}>
              <dt className="text-muted">{signal.replace(/_/g, ' ')}</dt>
              <dd className="tabular-nums text-secondary">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </li>
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
      return '/discover';
  }
}
