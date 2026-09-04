import { AgentCard } from '@/components/agents/AgentCard';
import { ErrorState } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import type { AgentCard as AgentCardData } from '@/lib/types';

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

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 className="text-xl font-semibold text-primary">AI agents</h1>
          <p className="mt-3xs text-sm text-secondary">
            Every agent here answers on certified KPI definitions, over data products it is
            bound to, and says what it will not do.
          </p>
        </div>
        <nav aria-label="Sort agents" className="flex flex-wrap gap-2xs">
          {SORTS.map((option) => {
            const next = new URLSearchParams();
            for (const [key, values] of Object.entries(selected)) {
              for (const value of values) next.append(key, value);
            }
            next.set('sort', option.code);
            return (
              <a
                key={option.code}
                href={`/agents?${next.toString()}`}
                aria-current={sort === option.code ? 'true' : undefined}
                className="rounded-pill border border-subtle px-sm py-3xs text-2xs text-secondary aria-[current]:border-accent aria-[current]:text-accent"
              >
                {option.label}
              </a>
            );
          })}
        </nav>
      </header>

      {page.items.length === 0 ? (
        <div className="rounded-lg border border-subtle bg-sunken p-2xl text-center">
          <p className="text-sm font-medium text-primary">No agent matches those filters.</p>
          <p className="mt-2xs text-sm text-secondary">
            Clear a filter, or file the question you came here with as demand — an unanswered
            question is the most useful thing the marketplace can learn about itself.
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
    </div>
  );
}
