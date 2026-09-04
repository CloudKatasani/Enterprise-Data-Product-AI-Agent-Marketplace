import Link from 'next/link';

import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { HealthPlane, ValuePlane } from '@/lib/types';
import { inUnit, UNIT_FRACTION, UNIT_MULTIPLE } from '@/lib/units';

export const dynamic = 'force-dynamic';

const TABS = [
  { code: 'health', label: 'Health' },
  { code: 'value', label: 'Value' },
  { code: 'cost', label: 'Cost' },
] as const;

/**
 * The health and money planes on one page (M10).
 *
 * Findings and incidents are separate things and shown separately. A finding is
 * a detector saying a number crossed a line; an incident is the estate having
 * decided that matters, with a severity computed from who is downstream. Merging
 * them would make severity look like an opinion about a metric.
 */
export default async function ObservabilityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const tab = typeof params.tab === 'string' ? params.tab : 'health';

  const [healthResult, valueResult] = await Promise.all([
    apiTry<HealthPlane>('/observability'),
    apiTry<ValuePlane>('/value'),
  ]);

  if (!healthResult.ok) {
    return (
      <PageMessage title="The health plane is unavailable">
        {healthResult.problem.detail}
      </PageMessage>
    );
  }

  const health = healthResult.data;
  const value = valueResult.ok ? valueResult.data : null;

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg">
        <h1 className="text-xl font-semibold text-primary">Observability</h1>
        <p className="mt-3xs max-w-3xl text-sm text-secondary">
          What is wrong, what it is worth, and what it costs. Severity is computed from
          who is downstream, never chosen — and an owner can add context to an incident
          but cannot stop their consumers being told.
        </p>
      </header>

      <nav aria-label="Sections" className="border-b border-subtle">
        <ul className="flex flex-wrap gap-3xs">
          {TABS.map((entry) => (
            <li key={entry.code}>
              <Link
                href={`/observability?tab=${entry.code}`}
                aria-current={tab === entry.code ? 'page' : undefined}
                className="inline-flex border-b-2 border-transparent px-md py-sm text-sm text-secondary aria-[current]:border-accent aria-[current]:text-accent"
              >
                {entry.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="py-lg">
        {tab === 'value' ? (
          <ValueTab value={value} />
        ) : tab === 'cost' ? (
          <CostTab value={value} />
        ) : (
          <HealthTab health={health} />
        )}
      </div>

      <p className="mt-xl text-2xs text-muted">
        Signals evaluated under rubric{' '}
        <span className="font-mono">{health.rubric_version_id}</span>
        {value ? (
          <>
            {' '}· value under <span className="font-mono">{value.rubric_version_id}</span>
          </>
        ) : null}
        .
      </p>
    </div>
  );
}

function HealthTab({ health }: { health: HealthPlane }) {
  return (
    <div className="space-y-xl">
      {health.overdue_notifications.length > 0 ? (
        <section className="incident-banner" data-severity="sev1">
          <p className="incident-headline">
            {health.overdue_notifications.length} incident(s) missed the consumer
            notification deadline.
          </p>
          <p className="incident-detail">
            That deadline is the one thing consumers are promised about incidents. A
            miss is itself an incident.
          </p>
        </section>
      ) : null}

      <section>
        <h2 className="refusal-subhead">Open incidents</h2>
        {health.incidents.length === 0 ? (
          <p className="mt-2xs rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
            Nothing is open. Every signal below is currently inside its threshold.
          </p>
        ) : (
          <div className="answer-table-wrap mt-2xs">
            <table className="answer-table">
              <caption className="sr-only">Open incidents</caption>
              <thead>
                <tr>
                  <th scope="col">Severity</th>
                  <th scope="col">Asset</th>
                  <th scope="col">Signal</th>
                  <th scope="col">Guarantee breached</th>
                  <th scope="col">Listings bannered</th>
                  <th scope="col">Detected</th>
                </tr>
              </thead>
              <tbody>
                {health.incidents.map((incident) => (
                  <tr key={incident.incident_id}>
                    <td>
                      <span
                        className="incident-severity"
                        data-severity={incident.severity}
                      >
                        {incident.severity}
                      </span>
                    </td>
                    <td>{incident.asset_id}</td>
                    <td>{incident.signal.replace(/_/g, ' ')}</td>
                    <td>{incident.guarantee_breached ?? '—'}</td>
                    <td className="tabular-nums">{incident.impacted}</td>
                    <td>{incident.detected_at.split('T')[0]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="refusal-subhead">Findings</h2>
        <p className="mt-2xs mb-md text-sm text-secondary">
          What the detectors saw. A finding is a number crossing a line; an incident is
          the estate deciding that matters and working out who it reaches.
        </p>
        {health.findings.length === 0 ? (
          <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
            Every signal is inside its threshold.
          </p>
        ) : (
          <ul className="space-y-2xs">
            {health.findings.map((finding) => (
              <li
                key={`${finding.asset_id}-${finding.signal}`}
                className="rounded-md border border-subtle p-md"
              >
                <p className="text-2xs uppercase tracking-wide text-muted">
                  {finding.signal.replace(/_/g, ' ')} · {finding.asset_id}
                </p>
                <p className="mt-2xs text-sm text-secondary">{finding.detail}</p>
                <p className="mt-3xs text-2xs tabular-nums text-muted">
                  observed {inUnit(finding.observed, finding.unit)} against a threshold
                  of {inUnit(finding.threshold, finding.unit)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ValueTab({ value }: { value: ValuePlane | null }) {
  if (value === null) {
    return <p className="text-sm text-secondary">The value plane is unavailable.</p>;
  }
  return (
    <div className="answer-table-wrap">
      <table className="answer-table">
        <caption className="sr-only">Value by agent</caption>
        <thead>
          <tr>
            <th scope="col">Agent</th>
            <th scope="col">Answered</th>
            <th scope="col">Acceptance</th>
            <th scope="col">Hours saved</th>
            <th scope="col">Value</th>
            <th scope="col">Cost</th>
            <th scope="col">Net</th>
            <th scope="col">Ratio</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {value.portfolio.map((item) => (
            <tr key={item.asset_id}>
              <td>
                <Link href={`/agents/${item.asset_id}`} className="hover:underline">
                  {item.asset_id}
                </Link>
              </td>
              <td className="tabular-nums">{item.answered}</td>
              <td className="tabular-nums">
                {inUnit(item.acceptance_rate, UNIT_FRACTION)}
              </td>
              <td className="tabular-nums">{item.deflected_hours}</td>
              <td className="tabular-nums">${item.deflected_value_usd.toLocaleString()}</td>
              <td className="tabular-nums">${item.total_cost_usd.toLocaleString()}</td>
              <td className="tabular-nums">${item.net_value_usd.toLocaleString()}</td>
              <td className="tabular-nums">
                {item.value_ratio === null
                  ? '—'
                  : inUnit(item.value_ratio, UNIT_MULTIPLE)}
              </td>
              {/* Section 15.7: the sample size is shown next to any figure
                  derived from it. A deflection estimate is an argument, and an
                  argument without its evidence is a large number nobody can
                  check. */}
              <td className="text-2xs text-muted">
                {item.evidence.length === 0
                  ? '—'
                  : item.evidence
                      .slice(0, item.evidence.length)
                      .map((entry) => `n=${entry.sample_size} (${entry.question_class})`)
                      .join(', ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CostTab({ value }: { value: ValuePlane | null }) {
  if (value === null) {
    return <p className="text-sm text-secondary">The cost plane is unavailable.</p>;
  }
  return (
    <div className="space-y-xl">
      <section>
        <h2 className="refusal-subhead">Unit economics</h2>
        <p className="mt-2xs mb-md max-w-3xl text-sm text-secondary">
          Cost per <em>accepted</em> answer is the comparable number. An agent answering
          cheaply and being rejected half the time is not a cheap agent; it is an
          expensive one with a flattering denominator.
        </p>
        <div className="answer-table-wrap">
          <table className="answer-table">
            <caption className="sr-only">Unit economics by agent</caption>
            <thead>
              <tr>
                <th scope="col">Agent</th>
                <th scope="col">Answered</th>
                <th scope="col">Marginal / answer</th>
                <th scope="col">Budget</th>
                <th scope="col">Loaded / answer</th>
                <th scope="col">Loaded / accepted</th>
                <th scope="col">Within budget</th>
              </tr>
            </thead>
            <tbody>
              {value.unit_economics.map((item) => (
                <tr key={item.agent_id}>
                  <td>{item.agent_id}</td>
                  <td className="tabular-nums">{item.answered}</td>
                  <td className="tabular-nums">
                    {item.marginal_cost_per_answer_usd === null
                      ? '—'
                      : `$${item.marginal_cost_per_answer_usd}`}
                  </td>
                  <td className="tabular-nums">${item.budget_per_answer_usd}</td>
                  <td className="tabular-nums">
                    {item.cost_per_answer_usd === null
                      ? '—'
                      : `$${item.cost_per_answer_usd}`}
                  </td>
                  <td className="tabular-nums">
                    {item.cost_per_accepted_answer_usd === null
                      ? '—'
                      : `$${item.cost_per_accepted_answer_usd}`}
                  </td>
                  <td>{item.within_budget ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="refusal-subhead">Retirement candidates</h2>
        {value.retirement_candidates.length === 0 ? (
          <p className="mt-2xs rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
            Nothing in the estate is both unused and expensive. Something unused and
            free is not worth a meeting.
          </p>
        ) : (
          <ul className="mt-2xs space-y-2xs">
            {value.retirement_candidates.map((item) => (
              <li key={item.asset_id} className="rounded-md border border-subtle p-md">
                <p className="text-sm font-medium text-primary">{item.asset_id}</p>
                <p className="mt-3xs text-sm text-secondary">{item.why}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="refusal-subhead">Demo spend</h2>
        <p className="mt-2xs text-sm text-secondary">
          {value.demo_tier_share.share_pct}% of inference spend goes on demos,
          against a cap of {value.demo_tier_share.cap_pct}%.{' '}
          {value.demo_tier_share.within_cap
            ? 'Within the cap.'
            : 'Over the cap — a marketplace whose theatre costs more than its traffic is selling something it does not run.'}
        </p>
      </section>
    </div>
  );
}
