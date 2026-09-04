import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import type { AgentCard as AgentCardData } from '@/lib/types';

/**
 * The agent card.
 *
 * It answers the product card's questions in the product card's order, with one
 * addition that sits above the fold rather than in a tab: what the agent will
 * not do. For a data product, scope is a schema question; for an agent it is
 * the first thing a buyer needs, because an agent that answers confidently
 * outside its competence is the failure mode everyone is afraid of.
 */
export function AgentCard({ agent }: { agent: AgentCardData }) {
  const href = `/agents/${agent.agent_id}`;
  const evaluation = agent.evaluation;

  return (
    <li className="product-card">
      <div className="flex items-start justify-between gap-sm">
        <div className="min-w-0">
          <h3 className="truncate text-md font-semibold text-primary">
            <Link href={href} className="hover:underline">
              {agent.name}
            </Link>
          </h3>
          <p className="mt-3xs text-2xs uppercase tracking-wide text-muted">
            {agent.industry.replace(/_/g, ' ')} · {agent.domain.replace(/_/g, ' ')} ·{' '}
            autonomy {agent.autonomy_level}
          </p>
        </div>
        <Badge tone="certification" code={agent.certification}>
          {agent.certification}
        </Badge>
      </div>

      <p className="mt-sm line-clamp-3 text-sm text-secondary">{agent.capability_statement}</p>

      <div className="mt-sm">
        <p className="text-2xs uppercase tracking-wide text-muted">Will not</p>
        <ul className="card-limit-list mt-3xs space-y-3xs">
          {agent.out_of_scope.map((limit) => (
            <li key={limit} className="text-2xs text-band-watch">
              {limit}
            </li>
          ))}
        </ul>
      </div>

      <dl className="mt-md grid grid-cols-2 gap-2xs text-2xs">
        <Stat label="KPIs answered" value={String(agent.coverage.kpis)} />
        <Stat label="Data products" value={String(agent.coverage.data_products)} />
        <Stat
          label="Groundedness"
          value={
            evaluation.groundedness_pct === null
              ? 'not evaluated'
              : `${evaluation.groundedness_pct}%`
          }
        />
        <Stat label="Answers, 30d" value={agent.adoption.answers_30d.toLocaleString()} />
      </dl>

      <div className="mt-md flex items-center justify-between gap-sm border-t border-subtle pt-sm">
        <span className="text-2xs text-muted">
          {agent.demo.validated_exchanges} validated demo question
          {agent.demo.validated_exchanges === 1 ? '' : 's'}
        </span>
        {agent.access.granted ? (
          <Link href={`${href}/demo`} className="text-2xs font-medium text-accent hover:underline">
            Try it
          </Link>
        ) : (
          <Link
            href={agent.access.request_access_url}
            className="text-2xs font-medium text-accent hover:underline"
            title={agent.access.required_scope}
          >
            Request access
          </Link>
        )}
      </div>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-3xs font-medium text-primary">{value}</dd>
    </div>
  );
}
