import Link from 'next/link';

import type { SupplyAssessment } from '@/lib/types';

/**
 * What the estate can already answer, and what to do about it.
 *
 * The recommendation leads, because it is the only part a requester has to act
 * on. Everything under it is the evidence it was made from — which KPIs are
 * answered by what, which are not answered at all, and which questions nothing
 * could place. A recommendation that cannot be argued with gets overridden the
 * first time somebody disagrees and ignored every time after, so the disagreement
 * is made cheap: the rows are right there.
 */
const TONE: Record<string, string> = {
  already_served: 'assessment-verdict-served',
  enhance_agent: 'assessment-verdict-enhance',
  enhance_product: 'assessment-verdict-enhance',
  build_new: 'assessment-verdict-build',
  insufficient_evidence: 'assessment-verdict-thin',
};

const ACTION: Record<string, string> = {
  already_served: 'Request access instead',
  enhance_agent: 'File it as an enhancement',
  enhance_product: 'File it as an enhancement',
  build_new: 'File it as new demand',
  insufficient_evidence: 'Name the KPIs and check again',
};

function href(assessment: SupplyAssessment): string | null {
  const best = assessment.candidates[0];
  if (assessment.recommendation === 'already_served' && best) {
    return `/requests/new/access?asset=${best.asset_id}&surface=${best.asset_type}`;
  }
  if (
    (assessment.recommendation === 'enhance_agent' ||
      assessment.recommendation === 'enhance_product') &&
    best
  ) {
    return `/requests/new/enhancement?asset=${best.asset_id}`;
  }
  return null;
}

export function AssessmentPanel({ assessment }: { assessment: SupplyAssessment }) {
  const target = href(assessment);
  const answered = assessment.coverage.filter((row) => row.answered);
  const unanswered = assessment.coverage.filter((row) => !row.answered);

  return (
    <section className={`assessment ${TONE[assessment.recommendation] ?? ''}`}>
      <p className="text-2xs uppercase tracking-wide text-muted">
        Assessed against the estate
      </p>
      <h2 className="mt-3xs text-md font-semibold text-primary">{assessment.headline}</h2>
      <p className="mt-2xs text-sm text-secondary">{assessment.rationale}</p>

      {target ? (
        <Link href={target} className="refusal-action mt-md inline-flex">
          {ACTION[assessment.recommendation]}
        </Link>
      ) : null}

      {assessment.coverage.length > 0 ? (
        <div className="mt-lg grid grid-cols-1 gap-lg sm:grid-cols-2">
          <div>
            <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
              Already answered ({answered.length})
            </h3>
            <ul className="mt-xs space-y-3xs text-sm">
              {answered.length === 0 ? (
                <li className="text-2xs text-muted">none</li>
              ) : (
                answered.map((row) => (
                  <li key={row.kpi_id} className="text-secondary">
                    <span className="font-mono text-2xs text-primary">{row.kpi_id}</span>{' '}
                    {row.kpi_name ? `— ${row.kpi_name} ` : ''}
                    <span className="text-2xs">by {row.answered_by.join(', ')}</span>
                  </li>
                ))
              )}
            </ul>
          </div>
          <div>
            <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
              Answered by nothing ({unanswered.length})
            </h3>
            <ul className="mt-xs space-y-3xs text-sm">
              {unanswered.length === 0 ? (
                <li className="text-2xs text-muted">none</li>
              ) : (
                unanswered.map((row) => (
                  <li key={row.kpi_id} className="text-secondary">
                    <span className="font-mono text-2xs text-primary">{row.kpi_id}</span>{' '}
                    {row.known ? (
                      <span className="text-2xs">
                        published by {row.source_product_id ?? 'no product'}, no agent
                        answers it
                      </span>
                    ) : (
                      <span className="text-2xs">not in the KPI register</span>
                    )}
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      ) : null}

      {assessment.candidates.length > 0 ? (
        <div className="mt-lg">
          <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
            Closest existing assets
          </h3>
          <table className="assessment-table mt-xs">
            <caption className="sr-only">
              Existing agents and data products ranked by how much of what was
              asked for they already cover
            </caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Covers</th>
                <th scope="col">Missing</th>
              </tr>
            </thead>
            <tbody>
              {assessment.candidates.map((candidate) => (
                <tr key={`${candidate.asset_type}-${candidate.asset_id}`}>
                  <th scope="row">
                    <span className="font-mono text-2xs">{candidate.asset_id}</span>{' '}
                    {candidate.name}
                  </th>
                  <td className="tabular-nums">
                    {candidate.covered_kpis.length} of{' '}
                    {candidate.covered_kpis.length + candidate.missing_kpis.length}
                  </td>
                  <td className="text-2xs text-secondary">
                    {candidate.missing_kpis.join(', ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {assessment.unplaced_questions.length > 0 ? (
        <div className="mt-lg">
          <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
            Questions naming no certified measure
          </h3>
          <ul className="mt-xs space-y-3xs text-sm text-secondary">
            {assessment.unplaced_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
          {/* Placement is by measure name and synonym, the way the runtime does
              it, so a question phrased around the decision rather than the
              measure lands here even when an agent could answer it. Saying so
              is the difference between evidence and a wrong verdict. */}
          <p className="mt-2xs text-2xs text-muted">
            Matched against KPI names and their synonyms. A question phrased
            around the decision rather than the measure lands here even when an
            agent could answer it.
          </p>
        </div>
      ) : null}

      {assessment.notes.length > 0 ? (
        <ul className="mt-md space-y-3xs text-2xs text-muted">
          {assessment.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
