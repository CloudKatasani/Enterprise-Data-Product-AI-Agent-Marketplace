import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import type { FeaturedAgent } from '@/lib/types';

/**
 * Meet the agents (band 5) — the conversion band.
 *
 * Each card carries what an agent will and will not do. The out-of-scope line
 * is not a disclaimer added for balance: an agent that cannot say what it does
 * not do has not been described, and the publish gate refuses to let one
 * through without it. Showing it here is showing the thing itself.
 *
 * "Try a question" goes to the demo console for that agent rather than opening
 * a modal that reimplements it. One console, one code path, one set of
 * groundedness rules.
 */
export function AgentCarousel({ agents }: { agents: FeaturedAgent[] }) {
  if (agents.length === 0) return null;

  return (
    <section className="agents-band" aria-labelledby="agents-heading">
      <h2 id="agents-heading" className="band-heading">
        Meet the agents
      </h2>
      <p className="band-sub">
        Each one is catalogued like any other asset: an owner, a coverage map, an
        evaluation suite and a value case. What it will not do is on the card.
      </p>
      <ul className="agent-strip" role="list">
        {agents.map((agent) => (
          <li key={agent.agent_id} className="agent-tile">
            <div className="flex items-start justify-between gap-sm">
              <h3 className="text-md font-semibold text-primary">
                <Link href={`/agents/${agent.agent_id}`} className="hover:underline">
                  {agent.name}
                </Link>
              </h3>
              <Badge tone="certification" code={agent.certification}>
                {agent.certification}
              </Badge>
            </div>
            <p className="mt-3xs text-2xs uppercase tracking-wide text-muted">
              {agent.industry.replace(/_/g, ' ')} · autonomy {agent.autonomy_level}
            </p>
            <p className="mt-2xs text-sm text-secondary">{agent.capability_statement}</p>
            {agent.out_of_scope ? (
              <p className="mt-2xs text-xs text-muted">
                <span className="font-medium">Will not:</span> {agent.out_of_scope}
              </p>
            ) : null}
            <p className="mt-2xs text-xs text-muted">
              Runs on {agent.products.join(', ') || 'no published product'}
            </p>
            <Link href={`/agents/${agent.agent_id}/demo`} className="agent-try">
              Try a question
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
