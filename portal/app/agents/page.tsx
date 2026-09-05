import Link from 'next/link';

import { AgentCard } from '@/components/agents/AgentCard';
import { FacetRail } from '@/components/catalog/FacetRail';
import { ErrorState } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import type { AgentCard as AgentCardData, Facet } from '@/lib/types';

export const dynamic = 'force-dynamic';

const FILTER_KEYS = ['industry', 'domain', 'autonomy', 'certification', 'kpi', 'product'] as const;

const SORTS = [
  { code: 'name', label: 'Name' },
  { code: 'coverage', label: 'KPIs answered' },
  { code: 'adoption', label: 'Adoption' },
  { code: 'quality', label: 'Evaluation' },
] as const;

interface AgentsPage {
  items: AgentCardData[];
  next_cursor: string | null;
  total: number | null;
  facets: Facet[];
  sort: string;
}

type SearchParams = Record<string, string | string[] | undefined>;

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

export default async function AgentsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const selected: Record<string, string[]> = {};
  for (const key of FILTER_KEYS) {
    const values = asList(params[key]);
    if (values.length > 0) selected[key] = values;
  }
  const sort = typeof params.sort === 'string' ? params.sort : 'name';
  const cursor = typeof params.cursor === 'string' ? params.cursor : undefined;

  const result = await apiTry<AgentsPage>('/agents', { ...selected, sort, cursor });

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <ErrorState title="The agent catalog is unavailable" detail={result.problem.detail} />
      </div>
    );
  }

  const page = result.data;
  const chosen = Object.entries(selected).flatMap(([key, values]) =>
    values.map((value) => [key, value] as const),
  );

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 className="text-xl font-semibold text-primary">AI agents</h1>
          <p className="mt-3xs text-sm text-secondary">
            {page.total} governed agents. Every one answers on certified KPI definitions, over
            data products it is bound to, and says what it will not do.
          </p>
        </div>
        <nav aria-label="Sort agents" className="flex flex-wrap gap-2xs">
          {SORTS.map((option) => (
            <Link
              key={option.code}
              href={hrefWith(selected, { sort: option.code })}
              aria-current={sort === option.code ? 'true' : undefined}
              className="rounded-pill border border-subtle px-sm py-3xs text-2xs text-secondary aria-[current]:border-accent aria-[current]:text-accent"
            >
              {option.label}
            </Link>
          ))}
        </nav>
      </header>

      <div className="grid grid-cols-1 gap-xl lg:grid-cols-[240px_1fr]">
        <aside>
          {chosen.length > 0 ? (
            <div className="mb-lg">
              <h2 className="text-2xs font-semibold uppercase tracking-wide text-muted">
                Filtering by
              </h2>
              <ul className="mt-xs flex flex-wrap gap-2xs">
                {chosen.map(([key, value]) => (
                  <li key={`${key}:${value}`}>
                    <Link
                      href={hrefWithout(selected, key, value)}
                      className="inline-flex items-center gap-2xs rounded-pill border border-subtle bg-sunken px-sm py-3xs text-2xs text-primary hover:border-strong"
                    >
                      <span>{value.replace(/_/g, ' ')}</span>
                      <span aria-hidden="true">&times;</span>
                      <span className="sr-only">Remove this filter</span>
                    </Link>
                  </li>
                ))}
              </ul>
              <Link
                href="/agents"
                className="mt-xs inline-block text-2xs text-secondary underline hover:text-primary"
              >
                Clear all
              </Link>
            </div>
          ) : null}
          <FacetRail facets={page.facets ?? []} selected={selected} basePath="/agents" />
        </aside>

        <div>
          {page.items.length === 0 ? (
            <div className="rounded-lg border border-subtle bg-sunken p-2xl text-center">
              <p className="text-sm font-medium text-primary">No agent matches those filters.</p>
              <p className="mt-2xs text-sm text-secondary">
                Clear a filter, or file the question you came here with as demand — an
                unanswered question is the most useful thing the marketplace can learn about
                itself.
              </p>
              <a href="/requests/new/supply" className="refusal-action mt-md inline-flex">
                File it as demand
              </a>
            </div>
          ) : (
            <ul className="grid grid-cols-1 gap-md sm:grid-cols-2 xl:grid-cols-3">
              {page.items.map((agent) => (
                <AgentCard key={agent.agent_id} agent={agent} />
              ))}
            </ul>
          )}

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
  return query ? `/agents?${query}` : '/agents';
}

function hrefWithout(
  selected: Record<string, string[]>,
  code: string,
  value: string,
): string {
  const params = new URLSearchParams();
  for (const [key, values] of Object.entries(selected)) {
    for (const item of values) {
      if (key === code && item === value) continue;
      params.append(key, item);
    }
  }
  const query = params.toString();
  return query ? `/agents?${query}` : '/agents';
}
