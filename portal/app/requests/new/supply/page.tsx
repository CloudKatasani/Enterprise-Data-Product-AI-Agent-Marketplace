import Link from 'next/link';

import { AssessmentPanel } from '@/components/workflow/AssessmentPanel';
import { DuplicatePanel } from '@/components/workflow/DuplicatePanel';
import { apiPost } from '@/lib/api';
import type { AssessResponse } from '@/lib/types';

export const dynamic = 'force-dynamic';

const KINDS = [
  { code: 'data_product', label: 'A data product' },
  { code: 'agent', label: 'An AI agent' },
] as const;

type DemandKind = (typeof KINDS)[number]['code'];

/**
 * A kind off the query string is whatever somebody typed there. Narrowing it
 * against the list the form offers means an edited URL falls back to the
 * default rather than sending the API a kind it will refuse.
 */
function asKind(value: string | string[] | undefined): DemandKind {
  return KINDS.some((option) => option.code === value)
    ? (value as DemandKind)
    : KINDS[0].code;
}

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

/** Newline- or comma-separated free text, as the list the caller meant. */
function lines(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * New-supply intake (section 14.3).
 *
 * Two checks run on what has been typed, before anything is filed, because this
 * is the moment the person is actually motivated to look:
 *
 * * the duplicate check asks whether the request *reads like* something that
 *   exists — a similarity, over the description and the entities named;
 * * the supply assessment asks whether the estate can already *answer* it — a
 *   coverage fact, over the KPIs and questions named.
 *
 * The second is why the form asks for KPIs and example questions rather than a
 * description alone. A demand that cannot name a measure cannot be checked
 * against the coverage map, and the assessment says so instead of guessing.
 *
 * The form is a GET back to this page, so every state is a URL somebody can
 * share with the steward they are arguing with, and none of it needs JavaScript.
 */
export default async function NewSupplyRequestPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const text = typeof params.question === 'string' ? params.question : '';
  const declinedBy = typeof params.declined_by === 'string' ? params.declined_by : '';
  const kind = asKind(params.kind);
  const kpiText = typeof params.kpis === 'string' ? params.kpis : '';
  const questionText = typeof params.questions === 'string' ? params.questions : '';
  const entities = asList(params.entity);
  const sources = asList(params.source);

  const kpis = lines(kpiText);
  const questions = lines(questionText);
  const asked = text || kpis.length > 0 || questions.length > 0;

  const result = asked
    ? await apiPost<AssessResponse>('/demand/assess', {
        kind,
        text,
        kpis,
        questions,
        entities,
        sources,
      })
    : null;

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
          : 'Describe what you need and name the measures it would have to carry. Before anything is filed, we check whether the estate already answers it.'}
      </p>

      <form method="get" className="supply-form mt-lg">
        <fieldset>
          <legend className="text-2xs font-semibold uppercase tracking-wide text-muted">
            What are you asking for?
          </legend>
          <div className="mt-xs flex flex-wrap gap-md">
            {KINDS.map((option) => (
              <label
                key={option.code}
                htmlFor={`kind-${option.code}`}
                className="flex items-center gap-2xs text-sm"
              >
                {/* The wrapping label associates these already; the explicit
                    pair and the aria-label are what the a11y check can see,
                    because the id is built from the option rather than
                    written out. */}
                <input
                  id={`kind-${option.code}`}
                  type="radio"
                  name="kind"
                  value={option.code}
                  aria-label={option.label}
                  defaultChecked={kind === option.code}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <p>
          <label htmlFor="question" className="supply-label">
            What do you need, and what decision does it serve?
          </label>
          <textarea
            id="question"
            name="question"
            defaultValue={text}
            className="supply-input supply-input--tall"
            placeholder="Freight margin by lane, so procurement can renegotiate the lanes that lose money."
          />
        </p>

        <p>
          <label htmlFor="kpis" className="supply-label">
            Which certified KPIs would the answer carry?
          </label>
          <textarea
            id="kpis"
            name="kpis"
            defaultValue={kpiText}
            className="supply-input supply-input--short font-mono"
            placeholder="KPI-FRTMARGIN-088, KPI-COSTPERKM-089"
          />
          <span className="supply-hint">
            One per line or comma separated. Without at least one, the estate cannot be
            checked for whether it already answers this —{' '}
            <Link href="/data-products" className="underline">
              browse the catalogue
            </Link>{' '}
            to find the identifiers.
          </span>
        </p>

        <p>
          <label htmlFor="questions" className="supply-label">
            Which questions would it have to answer?
          </label>
          <textarea
            id="questions"
            name="questions"
            defaultValue={questionText}
            className="supply-input supply-input--tall"
            placeholder="Which lanes are thinnest on margin?&#10;Do spot-tendered movements earn less?"
          />
          <span className="supply-hint">
            One per line. Each is checked against what the published agents can place.
          </span>
        </p>

        <button type="submit" className="refusal-action">
          Check it against the estate
        </button>
      </form>

      {result ? (
        <div className="mt-xl space-y-lg">
          {result.ok ? (
            <>
              <AssessmentPanel assessment={result.data.assessment} />
              {result.data.duplicates ? (
                <div>
                  <h2 className="refusal-subhead">Does it read like something we have?</h2>
                  <div className="mt-sm">
                    <DuplicatePanel check={result.data.duplicates} kind={kind} />
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-secondary">{result.problem.detail}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
