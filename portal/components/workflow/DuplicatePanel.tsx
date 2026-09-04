import Link from 'next/link';

import type { DuplicateCheck } from '@/lib/types';

/**
 * Duplicate-supply detection, shown side by side (section 14.3).
 *
 * The candidate is not a link and a score. A reviewer has to be able to
 * disagree with the call, so the panel shows which signal drove it, how much
 * evidence the comparison had, and every contributing factor — because a
 * duplicate check that cannot explain itself gets overridden once and then
 * ignored forever.
 */
export function DuplicatePanel({ check }: { check: DuplicateCheck }) {
  if (check.verdict === 'clear') {
    return (
      <section className="refusal-panel" data-kind="clear">
        <h2 className="refusal-title">Nothing in the estate covers this</h2>
        <p className="refusal-body">
          No existing data product scores close enough to be a duplicate. This request
          goes to scoring.
        </p>
      </section>
    );
  }

  const blocking = check.verdict === 'blocking';
  const architect = check.verdict === 'architect_review';

  return (
    <section
      className="refusal-panel"
      data-kind={blocking ? 'ungrounded' : undefined}
      aria-labelledby="duplicate-heading"
    >
      <h2 id="duplicate-heading" className="refusal-title">
        {blocking
          ? 'This may already exist'
          : architect
            ? 'Held for architect review'
            : 'Something similar already exists'}
      </h2>
      <p className="refusal-body">
        {blocking
          ? 'The request stops here until the owner of the candidate below has looked at it. If they agree it is different, it proceeds.'
          : architect
            ? 'The match scored high, but on thin evidence. An architect decides whether it is a real duplicate before it is shown as blocking.'
            : 'You can proceed. Worth a look first — someone may already have built this.'}
      </p>

      <div className="refusal-section">
        <h3 className="refusal-subhead">Candidates</h3>
        <ul className="mt-2xs space-y-sm">
          {check.matches.map((match) => (
            <li key={match.candidate_id} className="rounded-md border border-subtle p-md">
              <div className="flex flex-wrap items-baseline justify-between gap-2xs">
                <Link
                  href={`/data-products/${match.candidate_id}`}
                  className="text-sm font-medium text-accent hover:underline"
                >
                  {match.candidate_name}
                </Link>
                <span className="text-2xs tabular-nums text-muted">
                  similarity {match.similarity} · confidence {match.confidence}
                </span>
              </div>
              <p className="mt-2xs text-sm text-secondary">{match.rationale}</p>
              <dl className="mt-sm grid grid-cols-2 gap-2xs sm:grid-cols-4">
                {Object.entries(match.contributing_factors).map(([factor, value]) => (
                  <div key={factor}>
                    <dt className="text-2xs uppercase tracking-wide text-muted">
                      {factor.replace(/_/g, ' ')}
                    </dt>
                    <dd className="mt-3xs text-2xs tabular-nums text-primary">{value}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-lg text-2xs text-muted">
        Scored under rubric version{' '}
        <span className="font-mono">{check.rubric_version_id}</span>.
      </p>
    </section>
  );
}
