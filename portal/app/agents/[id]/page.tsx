import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ContextualRunbook } from '@/components/academy/ContextualRunbook';
import { AGENT_TABS, AgentTabPanel, type AgentDetail } from '@/components/agents/AgentTabs';
import { TabBar } from '@/components/detail/Tabs';
import { Badge } from '@/components/ui/Badge';
import { PermissionNotice } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import { NOT_FOUND } from '@/lib/http-status';
import type { AgentCard, CoverageRow, DemoExchange } from '@/lib/types';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function AgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const tab = typeof query.tab === 'string' ? query.tab : 'overview';

  const [cardResult, coverageResult, demoResult, evalResult] = await Promise.all([
    apiTry<{ card: AgentCard }>(`/agents/${id}`),
    apiTry<{ coverage: CoverageRow[] }>(`/agents/${id}/coverage`),
    apiTry<{ exchanges: DemoExchange[] }>(`/agents/${id}/demo`),
    apiTry<AgentDetail['evaluation']>(`/agents/${id}/evaluation`),
  ]);

  if (!cardResult.ok) {
    if (cardResult.problem.status === NOT_FOUND) notFound();
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <p className="text-sm text-secondary">{cardResult.problem.detail}</p>
      </div>
    );
  }

  const detail: AgentDetail = {
    card: cardResult.data.card,
    coverage: coverageResult.ok ? coverageResult.data.coverage : [],
    exchanges: demoResult.ok ? demoResult.data.exchanges : [],
    evaluation: evalResult.ok ? evalResult.data : { current: null },
  };
  const card = detail.card;

  // A tab with nothing in it says so in the bar, so nobody clicks through
  // seven tabs to find the two that are populated.
  const states = {
    overview: { state: 'populated' as const },
    capabilities: { state: detail.coverage.length ? ('populated' as const) : ('empty' as const) },
    demo: { state: detail.exchanges.length ? ('populated' as const) : ('empty' as const) },
    'data-products': {
      state: detail.coverage.length ? ('populated' as const) : ('empty' as const),
    },
    safety: { state: 'populated' as const },
    observability: { state: 'populated' as const },
    value: { state: 'empty' as const },
  };

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg">
        <p className="text-2xs uppercase tracking-wide text-muted">
          <Link href="/agents" className="hover:underline">
            Agents
          </Link>{' '}
          / {card.industry.replace(/_/g, ' ')}
        </p>
        <div className="mt-2xs flex flex-wrap items-start justify-between gap-md">
          <div>
            <h1 className="text-xl font-semibold text-primary">{card.name}</h1>
            <p className="mt-3xs max-w-3xl text-sm text-secondary">
              {card.capability_statement}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2xs">
            <Badge tone="certification" code={card.certification}>
              {card.certification}
            </Badge>
            <Badge tone="neutral" code={card.autonomy_level}>
              autonomy {card.autonomy_level}
            </Badge>
            {card.access.granted ? (
              <Link href={`/agents/${id}/demo`} className="refusal-action">
                Try it
              </Link>
            ) : null}
          </div>
        </div>
      </header>

      {card.access.granted ? null : (
        <div className="mb-lg">
          <PermissionNotice
            scope={card.access.required_scope}
            href={card.access.request_access_url}
            why="You can read everything about this agent. Asking it a question needs one more grant."
          />
        </div>
      )}

      <TabBar tabs={[...AGENT_TABS]} states={states} active={tab} basePath={`/agents/${id}`} />

      <div className="detail-body py-lg">
        <AgentTabPanel tab={tab} detail={detail} />
        {/* Section 20.2: what an agent will and will not do is the thing new
            consumers get wrong, so the module that explains it sits here. */}
        <ContextualRunbook assetType="agent" assetId={id} />
      </div>
    </div>
  );
}
