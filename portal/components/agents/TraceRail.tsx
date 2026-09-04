import type { AgentAnswer } from '@/lib/types';

/**
 * The tool-trace rail (BUILD.md M7.2).
 *
 * Visible by default, never behind a toggle. The reasoning is not decorative:
 * an answer's trustworthiness is a function of what it read and what that cost,
 * and hiding that behind an expander tells the reader it is a detail. It is
 * not — for most decisions it is the more important half of the page.
 *
 * Every number here comes from the execution the answer above it came from.
 * Nothing is estimated. A runtime that reports zero tokens reports zero tokens.
 */
export function TraceRail({ answer }: { answer: AgentAnswer }) {
  const { trace, citations, kpi_definitions: kpis, scope, tier } = answer;

  return (
    <aside className="trace-rail" aria-labelledby="trace-heading">
      <h2 id="trace-heading" className="text-2xs font-semibold uppercase tracking-wide text-muted">
        How this answer was produced
      </h2>

      <dl className="trace-figures">
        <Figure label="Rows scanned" value={trace.rows_scanned.toLocaleString()} />
        <Figure label="Latency" value={`${trace.latency_ms.toLocaleString()} ms`} />
        <Figure label="Cost" value={trace.cost_display} />
        <Figure label="Confidence" value={answer.confidence_display} />
        <Figure
          label="Tokens"
          value={
            trace.tokens.in === 0 && trace.tokens.out === 0
              ? 'none — no model called'
              : `${trace.tokens.in.toLocaleString()} in / ${trace.tokens.out.toLocaleString()} out`
          }
        />
        <Figure label="Runtime" value={trace.runtime} />
      </dl>

      <section className="trace-section">
        <h3 className="trace-subhead">Tool calls</h3>
        <ol className="trace-list">
          {trace.tool_calls.map((call, index) => (
            <li key={`${call.tool}-${index}`} className="trace-call">
              <p className="font-mono text-2xs text-primary">{call.tool}</p>
              <p className="text-2xs text-muted">
                {call.rows_returned.toLocaleString()} of{' '}
                {call.rows_scanned.toLocaleString()} rows · {call.duration_ms} ms ·{' '}
                {call.cost_class}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <section className="trace-section">
        <h3 className="trace-subhead">Read from</h3>
        <ul className="trace-list">
          {citations.map((citation) => (
            <li key={citation.product_id} className="trace-call">
              <p className="text-2xs font-medium text-primary">
                {citation.product_id}{' '}
                <span className="font-normal text-muted">v{citation.contract_version}</span>
              </p>
              <p className="text-2xs text-muted">
                {citation.columns.length} column{citation.columns.length === 1 ? '' : 's'}
                {citation.as_of ? ` · as of ${citation.as_of.slice(0, 10)}` : ''}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="trace-section">
        <h3 className="trace-subhead">Certified definitions</h3>
        <ul className="trace-chips">
          {kpis.map((kpi) => (
            <li key={kpi} className="trace-chip font-mono">
              {kpi}
            </li>
          ))}
        </ul>
      </section>

      <section className="trace-section">
        <h3 className="trace-subhead">Identity</h3>
        <p className="text-2xs text-muted">
          {scope.effective_scope === 'intersection'
            ? `Delegated: ${scope.agent_identity} acting for ${scope.on_behalf_of}. Effective access is the intersection of both.`
            : 'Direct: your own entitlement, no delegation.'}
        </p>
        <p className="mt-3xs text-2xs text-muted">
          Answered against the <strong className="text-secondary">{tier}</strong> tier.
        </p>
      </section>
    </aside>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="trace-figure">
      <dt className="text-2xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-3xs text-sm font-medium text-primary">{value}</dd>
    </div>
  );
}
