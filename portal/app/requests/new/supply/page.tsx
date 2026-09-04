import Link from 'next/link';

import { DuplicatePanel } from '@/components/workflow/DuplicatePanel';
import { apiPost } from '@/lib/api';
import type { DuplicateCheck } from '@/lib/types';

export const dynamic = 'force-dynamic';

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

function Named({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-3xs">
        {values.length === 0 ? (
          <span className="text-2xs text-muted">none given</span>
        ) : (
          <ul className="trace-chips">
            {values.map((value) => (
              <li key={value} className="trace-chip font-mono">
                {value}
              </li>
            ))}
          </ul>
        )}
      </dd>
    </div>
  );
}

/**
 * New-supply demand intake (section 14.3).
 *
 * The duplicate check runs on what has been typed so far, before anything is
 * filed. Catching a duplicate at this moment is worth more than any amount of
 * catalogue browsing, because it is the moment the person is actually
 * motivated to look.
 */
export default async function NewSupplyRequestPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const question = typeof params.question === 'string' ? params.question : '';
  const declinedBy = typeof params.declined_by === 'string' ? params.declined_by : '';
  const entities = asList(params.entity);
  const sources = asList(params.source);
  const kpis = asList(params.kpi);

  const check = question
    ? await apiPost<DuplicateCheck>('/demand/check', {
        text: question,
        entities,
        sources,
        kpis,
      })
    : null;
  // Text alone can reach at most the embedding weight — 0.40 under the current
  // rubric — which is below the advisory threshold by construction. So a
  // description with no entities, sources or KPIs named cannot raise even an
  // advisory, and saying "nothing covers this" on that basis would be a
  // stronger claim than the check can support.
  const thin = entities.length === 0 && sources.length === 0 && kpis.length === 0;

  return (
    <div className="mx-auto max-w-screen-md px-lg py-xl">
      <p className="text-2xs uppercase tracking-wide text-muted">
        <Link href="/demand" className="hover:underline">
          Demand
        </Link>{' '}
        / file new supply
      </p>
      <h1 className="mt-2xs text-xl font-semibold text-primary">
        Ask the estate for something new
      </h1>
      <p className="mt-2xs text-sm text-secondary">
        {declinedBy
          ? `${declinedBy} could not answer this. That is worth recording — an unanswered question is the most useful thing the marketplace can learn about itself.`
          : 'Describe what you need. Before anything is filed, we check whether the estate already supplies it.'}
      </p>

      {question ? (
        <blockquote className="mt-lg rounded-md border-l-2 border-accent bg-sunken px-md py-sm text-sm text-primary">
          {question}
        </blockquote>
      ) : (
        <p className="mt-lg rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
          Nothing to check yet. This form is normally reached from an agent that could
          not answer, or from a catalogue search that found nothing.
        </p>
      )}

      {check ? (
        <div className="mt-lg">
          {check.ok ? (
            <>
              {thin ? (
                <p className="mb-md rounded-md border border-subtle bg-sunken px-md py-sm text-2xs text-secondary">
                  Only the description was compared. Naming the entities, source systems
                  or KPIs you need makes this check far stronger — a description on its
                  own cannot carry enough evidence to flag a duplicate.
                </p>
              ) : null}
              <DuplicatePanel check={check.data} />
            </>
          ) : (
            <p className="text-sm text-secondary">{check.problem.detail}</p>
          )}
        </div>
      ) : null}

      <section className="mt-xl">
        <h2 className="refusal-subhead">What else are you asking for?</h2>
        <p className="mt-2xs text-sm text-secondary">
          These sharpen the duplicate check. Add them to the URL as{' '}
          <code className="font-mono text-2xs">entity=</code>,{' '}
          <code className="font-mono text-2xs">source=</code> or{' '}
          <code className="font-mono text-2xs">kpi=</code>, repeated per value.
        </p>
        <dl className="mt-sm grid grid-cols-1 gap-sm sm:grid-cols-3">
          <Named label="Entities" values={entities} />
          <Named label="Source systems" values={sources} />
          <Named label="KPIs" values={kpis} />
        </dl>
      </section>
    </div>
  );
}
