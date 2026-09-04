import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import type { PolicyEvaluation } from '@/lib/types';

/**
 * What will happen to this request, shown before it is submitted (section 14.1).
 *
 * The whole point of this panel is that it is not a guess. The API runs the same
 * evaluator at submission that produced this, so the path, the approvers and the
 * due date shown here are the ones the request will actually take — and the
 * policy version that decided is named, so a consumer surprised by an outcome
 * can look up the rules that produced it.
 *
 * A blocked request is not a failed form. It says which rule stopped it and,
 * where the estate has one, what to ask for instead.
 */
export function PolicyPreview({ evaluation }: { evaluation: PolicyEvaluation }) {
  return (
    <section
      className="refusal-panel"
      data-kind={evaluation.blocked ? 'ungrounded' : undefined}
      aria-labelledby="policy-preview-heading"
    >
      <div className="flex flex-wrap items-start justify-between gap-sm">
        <h2 id="policy-preview-heading" className="refusal-title">
          {evaluation.blocked ? 'Policy blocks this request' : evaluation.label}
        </h2>
        <Badge
          tone="sensitivity"
          code={evaluation.facts.sensitivity}
          title={`${evaluation.facts.asset_id} is classified ${evaluation.facts.sensitivity}`}
        >
          {evaluation.facts.sensitivity}
        </Badge>
      </div>

      <ul className="mt-sm space-y-3xs">
        {evaluation.reasons.map((reason) => (
          <li key={reason} className="refusal-body">
            {reason}
          </li>
        ))}
      </ul>

      {evaluation.blocked ? null : (
        <dl className="mt-lg grid grid-cols-2 gap-md sm:grid-cols-3">
          <div>
            <dt className="refusal-subhead">Approved by</dt>
            <dd className="mt-3xs text-sm text-primary">
              {evaluation.automatic
                ? 'Nobody — it provisions immediately'
                : evaluation.approvers.join(', then ')}
            </dd>
          </div>
          <div>
            <dt className="refusal-subhead">Decision due</dt>
            <dd className="mt-3xs text-sm text-primary">
              {evaluation.automatic
                ? 'Immediately'
                : `${evaluation.sla_days} business day${evaluation.sla_days === 1 ? '' : 's'}`}
            </dd>
          </div>
          <div>
            <dt className="refusal-subhead">Purpose</dt>
            <dd className="mt-3xs text-sm text-primary">
              {evaluation.facts.purpose_code.replace(/_/g, ' ')}
            </dd>
          </div>
        </dl>
      )}

      {evaluation.alternatives.length > 0 ? (
        <div className="refusal-section">
          <h3 className="refusal-subhead">You could ask for this instead</h3>
          <ul className="mt-2xs space-y-2xs">
            {evaluation.alternatives.map((alternative) => (
              <li key={alternative.product_id}>
                <Link
                  href={`/data-products/${alternative.product_id}`}
                  className="text-sm text-accent hover:underline"
                >
                  {alternative.name}
                </Link>
                <span className="ml-2xs text-2xs text-muted">{alternative.why}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-lg text-2xs text-muted">
        Decided by policy version{' '}
        <span className="font-mono">{evaluation.policy_version_id}</span>. The same
        evaluation runs when the request is submitted.
      </p>
    </section>
  );
}
