import Link from 'next/link';

import type { Problem } from '@/lib/api';

/**
 * The refusals, rendered as answers in their own right (BUILD.md M7.4).
 *
 * A refusal that reads as an error teaches the consumer that the product is
 * broken. A refusal that names the limit it hit, the agent that does cover the
 * question, and the form for asking for what is missing teaches them how the
 * estate is arranged. The second one is the product.
 *
 * Three shapes, one for each contract:
 *   422 out of scope     — the boundary, the agents that cover it, a demand link
 *   403 entitlement      — the exact scope, and a pre-filled access request
 *   424 ungrounded       — the answer was withheld, and why that is the right call
 */
export function RefusalPanel({ problem }: { problem: Problem }) {
  if (problem.type.endsWith('out_of_scope')) return <OutOfScope problem={problem} />;
  if (problem.type.endsWith('entitlement_missing')) return <Entitlement problem={problem} />;
  if (problem.type.endsWith('ungrounded_answer')) return <Ungrounded problem={problem} />;
  return (
    <section className="refusal-panel">
      <h2 className="refusal-title">This question could not be answered</h2>
      <p className="refusal-body">{problem.detail}</p>
    </section>
  );
}

function OutOfScope({ problem }: { problem: Problem }) {
  const suggested = (problem.suggested_agents as string[] | undefined) ?? [];
  const demandUrl = (problem.file_demand_url as string | undefined) ?? '/requests/new/supply';

  return (
    <section className="refusal-panel" data-kind="out-of-scope">
      <h2 className="refusal-title">Outside this agent&rsquo;s boundary</h2>
      <p className="refusal-body">{problem.detail}</p>

      {suggested.length > 0 ? (
        <div className="refusal-section">
          <h3 className="refusal-subhead">Agents that do cover this</h3>
          <ul className="trace-chips">
            {suggested.map((agentId) => (
              <li key={agentId}>
                <Link href={`/agents/${agentId}`} className="trace-chip hover:underline">
                  {agentId}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="refusal-section">
        <h3 className="refusal-subhead">Nothing covers it yet?</h3>
        <p className="refusal-body">
          File it as demand. Questions nobody can answer are the most useful thing the
          marketplace can know about itself.
        </p>
        <Link href={demandUrl} className="refusal-action">
          File this as demand
        </Link>
      </div>
    </section>
  );
}

function Entitlement({ problem }: { problem: Problem }) {
  return (
    <section className="refusal-panel" data-kind="entitlement">
      <h2 className="refusal-title">You need one more grant</h2>
      <p className="refusal-body">{problem.detail}</p>
      <p className="refusal-scope font-mono">{problem.required_scope}</p>
      {problem.request_access_url ? (
        <Link href={problem.request_access_url} className="refusal-action">
          Request this access
        </Link>
      ) : null}
    </section>
  );
}

function Ungrounded({ problem }: { problem: Problem }) {
  const count = (problem.uncited_claims as number | undefined) ?? 0;

  return (
    <section className="refusal-panel" data-kind="ungrounded">
      <h2 className="refusal-title">Answer withheld</h2>
      <p className="refusal-body">
        The agent produced an answer, and it was not sent. {count}{' '}
        {count === 1 ? 'number' : 'numbers'} in it could not be traced back to data the agent
        read.
      </p>
      <p className="refusal-body">
        An unciteable number is the most dangerous thing this system can produce, because it
        is the most believable. It is withheld rather than shown with a warning, and the
        agent&rsquo;s owner has been sent the record.
      </p>
    </section>
  );
}
