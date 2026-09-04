import Link from 'next/link';
import { notFound } from 'next/navigation';

import { AnswerPanel } from '@/components/agents/AnswerPanel';
import { RefusalPanel } from '@/components/agents/RefusalPanel';
import { TraceRail } from '@/components/agents/TraceRail';
import { PageMessage } from '@/components/ui/PageMessage';
import { apiPost, apiTry } from '@/lib/api';
import { NOT_FOUND } from '@/lib/http-status';
import type { AgentAnswer, AgentCard, DemoExchange } from '@/lib/types';

export const dynamic = 'force-dynamic';

const PURPOSE = 'analytics';
const TIER = 'demo';

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * The full-screen demo console (BUILD.md M7.1, M7.2, section 12).
 *
 * Two decisions worth stating.
 *
 * The exchange is chosen by URL, and asking runs on the server. That makes
 * every state of this page — an answer, a refusal, a withheld answer — a
 * shareable link, which is what a consumer evaluating an agent actually wants
 * to send to a colleague. It also means the answer arrives already validated:
 * there is no client-side moment where an ungrounded answer exists on screen.
 *
 * The trace rail sits beside the answer at every width above the fold, never
 * behind a disclosure. An answer's trustworthiness is a function of what it
 * read and what that cost.
 */
export default async function DemoConsolePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { id } = await params;
  const query = await searchParams;

  const [cardResult, demoResult] = await Promise.all([
    apiTry<{ card: AgentCard }>(`/agents/${id}`),
    apiTry<{ exchanges: DemoExchange[]; max_validation_age_days: number }>(
      `/agents/${id}/demo`,
    ),
  ]);

  if (!cardResult.ok) {
    if (cardResult.problem.status === NOT_FOUND) notFound();
    return <PageMessage title="Demo unavailable">{cardResult.problem.detail}</PageMessage>;
  }

  const card = cardResult.data.card;
  const exchanges = demoResult.ok ? demoResult.data.exchanges : [];

  const requested = typeof query.q === 'string' ? query.q : undefined;
  const selected =
    exchanges.find((exchange) => exchange.exchange_id === requested) ?? exchanges[0];

  if (!selected) {
    return (
      <PageMessage title={`${card.name} — demo console`}>
        No curated question is currently playable. An exchange appears here only while it is
        passing against its recorded answer and has been re-validated recently
        {demoResult.ok
          ? ` — inside the last ${demoResult.data.max_validation_age_days} days.`
          : '.'}
      </PageMessage>
    );
  }

  const result = await apiPost<AgentAnswer>(`/agents/${id}/ask`, {
    question: selected.question,
    exchange_id: selected.exchange_id,
    tier: TIER,
    purpose: PURPOSE,
    session_id: `SES-CONSOLE-${selected.exchange_id}`,
  });

  return (
    <div className="demo-console">
      <header className="demo-console-header">
        <div className="min-w-0">
          <p className="text-2xs uppercase tracking-wide text-muted">
            <Link href={`/agents/${id}`} className="hover:underline">
              {card.name}
            </Link>{' '}
            / demo console
          </p>
          <h1 className="mt-3xs truncate text-lg font-semibold text-primary">
            {selected.question}
          </h1>
        </div>
        <Link href={`/agents/${id}`} className="text-2xs text-accent hover:underline">
          Back to the agent
        </Link>
      </header>

      <nav aria-label="Curated questions" className="demo-question-picker">
        <ol className="flex flex-wrap gap-2xs">
          {exchanges.map((exchange) => (
            <li key={exchange.exchange_id}>
              <Link
                href={`/agents/${id}/demo?q=${exchange.exchange_id}`}
                aria-current={exchange.exchange_id === selected.exchange_id ? 'true' : undefined}
                className="demo-question-chip"
              >
                <span className="tabular-nums text-muted">{exchange.ordinal}.</span>{' '}
                {exchange.question}
              </Link>
            </li>
          ))}
        </ol>
      </nav>

      <div className="demo-console-body">
        <main className="demo-console-answer">
          {result.ok ? (
            <AnswerPanel answer={result.data} />
          ) : (
            <RefusalPanel problem={result.problem} />
          )}
        </main>
        {result.ok ? <TraceRail answer={result.data} /> : null}
      </div>
    </div>
  );
}
