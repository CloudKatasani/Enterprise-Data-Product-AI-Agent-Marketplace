import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import type { AgentCard, CoverageRow, DemoExchange } from '@/lib/types';

/**
 * The seven agent tabs (BUILD.md section 12).
 *
 * Overview | Capabilities | Demo | Data Products | Safety & Scope | Observability | Value
 *
 * Safety & Scope is a first-class tab rather than a footnote because for an
 * agent it carries the facts a reviewer needs before approving anything: the
 * declared boundary, the autonomy level, the bindings, and the evaluation
 * result that says whether any of it was checked.
 */

export interface AgentDetail {
  card: AgentCard;
  coverage: CoverageRow[];
  exchanges: DemoExchange[];
  evaluation: {
    current: {
      suite_results: {
        suite: string;
        blocking: boolean;
        pass_rate_pct: number;
        threshold_pct: number;
        passed: boolean;
        cases: number;
        failures: { case_id: string; detail: string }[];
      }[];
      pass_rate_pct: number;
      groundedness_pct: number;
      finished_at: string;
    } | null;
  };
}

export const AGENT_TABS = [
  { code: 'overview', label: 'Overview' },
  { code: 'capabilities', label: 'Capabilities' },
  { code: 'demo', label: 'Demo' },
  { code: 'data-products', label: 'Data Products' },
  { code: 'safety', label: 'Safety & Scope' },
  { code: 'observability', label: 'Observability' },
  { code: 'value', label: 'Value' },
] as const;

export function AgentTabPanel({ tab, detail }: { tab: string; detail: AgentDetail }) {
  switch (tab) {
    case 'capabilities':
      return <Capabilities detail={detail} />;
    case 'demo':
      return <Demo detail={detail} />;
    case 'data-products':
      return <DataProducts detail={detail} />;
    case 'safety':
      return <Safety detail={detail} />;
    case 'observability':
      return <Observability detail={detail} />;
    case 'value':
      return <Value />;
    default:
      return <Overview detail={detail} />;
  }
}

function Overview({ detail }: { detail: AgentDetail }) {
  const { card } = detail;
  return (
    <div className="space-y-lg">
      <section>
        <h2 className="tab-heading">What it does</h2>
        <p className="mt-2xs max-w-3xl text-sm text-secondary">{card.capability_statement}</p>
      </section>
      <section>
        <h2 className="tab-heading">Who it is for</h2>
        <ul className="mt-2xs trace-chips">
          {card.personas.map((persona) => (
            <li key={persona} className="trace-chip">
              {persona.replace(/_/g, ' ')}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="tab-heading">What it will not do</h2>
        <ul className="mt-2xs space-y-3xs">
          {card.out_of_scope.map((limit) => (
            <li key={limit} className="text-sm text-band-watch">
              {limit}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Capabilities({ detail }: { detail: AgentDetail }) {
  if (detail.coverage.length === 0) {
    return <Empty title="This version declares no coverage." />;
  }
  return (
    <div className="answer-table-wrap">
      <table className="answer-table">
        <caption className="sr-only">Certified KPIs this agent answers on</caption>
        <thead>
          <tr>
            <th scope="col">KPI</th>
            <th scope="col">Source product</th>
            <th scope="col">Grains</th>
            <th scope="col">Depth</th>
            <th scope="col">Eval accuracy</th>
            <th scope="col">Sample</th>
          </tr>
        </thead>
        <tbody>
          {detail.coverage.map((row) => (
            <tr key={row.kpi_id}>
              <td>
                <span className="font-mono text-2xs text-muted">{row.kpi_id}</span>
                <br />
                {row.kpi_name}
              </td>
              <td>
                <Link href={`/data-products/${row.source_product_id}`} className="hover:underline">
                  {row.source_product_id}
                </Link>
              </td>
              <td>{row.supported_grains.join(', ')}</td>
              <td>{row.analysis_depth}</td>
              <td className="tabular-nums">
                {row.eval_accuracy === null ? '—' : `${row.eval_accuracy}%`}
              </td>
              <td className="tabular-nums">{row.eval_sample_size ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Demo({ detail }: { detail: AgentDetail }) {
  if (detail.exchanges.length === 0) {
    return (
      <Empty title="No demo question is currently playable.">
        An exchange is only shown once it has been re-validated against its recorded answer.
        Silence is not evidence that it still works.
      </Empty>
    );
  }
  return (
    <div className="space-y-sm">
      <ol className="space-y-2xs">
        {detail.exchanges.map((exchange) => (
          <li key={exchange.exchange_id} className="rounded-md border border-subtle p-md">
            <p className="text-sm text-primary">{exchange.question}</p>
            <p className="mt-3xs text-2xs text-muted">
              <span className="font-mono">{exchange.kpi_class}</span> ·{' '}
              {exchange.analysis_type.replace(/_/g, ' ')}
              {exchange.last_validated
                ? ` · validated ${exchange.last_validated.slice(0, 10)}`
                : ''}
            </p>
          </li>
        ))}
      </ol>
      <Link href={`/agents/${detail.card.agent_id}/demo`} className="refusal-action inline-flex">
        Open the demo console
      </Link>
    </div>
  );
}

function DataProducts({ detail }: { detail: AgentDetail }) {
  const products = Array.from(new Set(detail.coverage.map((row) => row.source_product_id)));
  if (products.length === 0) return <Empty title="This version is bound to no product." />;
  return (
    <ul className="space-y-2xs">
      {products.map((productId) => {
        const rows = detail.coverage.filter((row) => row.source_product_id === productId);
        const columns = Array.from(new Set(rows.flatMap((row) => row.columns_used)));
        return (
          <li key={productId} className="rounded-md border border-subtle p-md">
            <Link
              href={`/data-products/${productId}`}
              className="text-sm font-medium text-primary hover:underline"
            >
              {productId}
            </Link>
            <p className="mt-3xs text-2xs text-muted">
              {columns.length} column{columns.length === 1 ? '' : 's'} read for{' '}
              {rows.length} KPI{rows.length === 1 ? '' : 's'}
            </p>
            <ul className="mt-2xs trace-chips">
              {columns.map((column) => (
                <li key={column} className="trace-chip font-mono">
                  {column}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

function Safety({ detail }: { detail: AgentDetail }) {
  const { card, evaluation } = detail;
  const run = evaluation.current;

  return (
    <div className="space-y-lg">
      <section>
        <h2 className="tab-heading">Autonomy and boundary</h2>
        <div className="mt-2xs flex flex-wrap gap-2xs">
          <Badge tone="neutral" code={card.autonomy_level}>
            autonomy {card.autonomy_level}
          </Badge>
          <Badge tone="certification" code={card.certification}>
            {card.certification}
          </Badge>
        </div>
        <ul className="mt-sm space-y-3xs">
          {card.out_of_scope.map((limit) => (
            <li key={limit} className="text-sm text-band-watch">
              {limit}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="tab-heading">Evaluation</h2>
        {run === null ? (
          <Empty title="This version has not been evaluated.">
            Nothing about its behaviour has been checked, which is why it is not published.
          </Empty>
        ) : (
          <div className="answer-table-wrap mt-2xs">
            <table className="answer-table">
              <caption className="sr-only">Evaluation suite results</caption>
              <thead>
                <tr>
                  <th scope="col">Suite</th>
                  <th scope="col">Result</th>
                  <th scope="col">Threshold</th>
                  <th scope="col">Cases</th>
                  <th scope="col">Blocking</th>
                </tr>
              </thead>
              <tbody>
                {run.suite_results.map((suite) => (
                  <tr key={suite.suite}>
                    <td>{suite.suite.replace(/_/g, ' ')}</td>
                    <td className="tabular-nums">
                      <Badge tone="band" code={suite.passed ? 'healthy' : 'at_risk'}>
                        {suite.pass_rate_pct}%
                      </Badge>
                    </td>
                    <td className="tabular-nums">{suite.threshold_pct}%</td>
                    <td className="tabular-nums">{suite.cases}</td>
                    <td>{suite.blocking ? 'yes' : 'advisory'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="tab-heading">Ownership</h2>
        <p className="mt-2xs text-sm text-secondary">
          {card.owner.name ?? card.owner.party_id}
          {card.owner.on_call ? ` · on call: ${card.owner.on_call}` : ''}
        </p>
      </section>
    </div>
  );
}

function Observability({ detail }: { detail: AgentDetail }) {
  const { card } = detail;
  return (
    <dl className="grid grid-cols-2 gap-md sm:grid-cols-4">
      <Figure label="Answers, 30 days" value={card.adoption.answers_30d.toLocaleString()} />
      <Figure label="Latency budget" value={`${card.budgets.p95_latency_ms} ms p95`} />
      <Figure
        label="Cost budget"
        value={`$${card.budgets.cost_per_answer_usd.toFixed(4)} per answer`}
      />
      <Figure
        label="Groundedness"
        value={
          card.evaluation.groundedness_pct === null
            ? 'not evaluated'
            : `${card.evaluation.groundedness_pct}%`
        }
      />
    </dl>
  );
}

function Value() {
  return (
    <Empty title="The value case lands with the value model.">
      This agent&rsquo;s benefit model, its assumptions and their sample sizes are recorded
      against its version and rendered here once the value plane is built.
    </Empty>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-3xs text-md font-medium text-primary">{value}</dd>
    </div>
  );
}

function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-subtle bg-sunken p-lg">
      <p className="text-sm font-medium text-primary">{title}</p>
      {children ? <p className="mt-2xs text-sm text-secondary">{children}</p> : null}
    </div>
  );
}
