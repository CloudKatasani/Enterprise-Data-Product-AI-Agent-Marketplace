import Link from 'next/link';

import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { AcademyIndex, AcademyMe } from '@/lib/types';
import { count } from '@/lib/units';

export const dynamic = 'force-dynamic';

/**
 * The academy (M12.1; specification section 20).
 *
 * Six paths, each ending in a certification that pre-approves an access tier
 * for its asset class. That last part is the reason anyone finishes: learning
 * here buys a shorter route to a grant, which is a concrete benefit rather than
 * a badge.
 *
 * Progress is shown against what the person actually holds, and a certification
 * that has expired is not shown as a certification. It stated what someone
 * understood about an estate that has since moved on.
 */
export default async function AcademyPage() {
  const [index, me] = await Promise.all([
    apiTry<AcademyIndex>('/academy/paths'),
    apiTry<AcademyMe>('/academy/me'),
  ]);

  if (!index.ok) {
    return <PageMessage title="Academy">{index.problem.detail}</PageMessage>;
  }

  const held = new Set(me.ok ? me.data.certifications.map((entry) => entry.code) : []);
  const progress = new Map(
    (me.ok ? me.data.progress : []).map((entry) => [entry.path_id, entry]),
  );

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg max-w-prose">
        <h1 className="text-xl font-semibold text-primary">Academy</h1>
        <p className="mt-3xs text-sm text-secondary">
          Adoption should not be gated on tribal knowledge. Every module runs against the
          demo tier, so a lesson is a real query or a real question rather than a
          description of one — and a certification pre-approves an access tier for its
          asset class, which is what makes finishing worth something.
        </p>
        <p className="mt-2xs text-2xs text-muted">
          Modules are passed at {index.data.pass_score_pct}%. A certification is good for{' '}
          {count(index.data.certification_valid_days, 'day', 'days')}, because it states
          what someone understood about an estate that keeps moving.
        </p>
      </header>

      <ul className="academy-grid" role="list">
        {index.data.paths.map((path) => {
          const state = progress.get(path.path_id);
          const certified = held.has(path.certification_code);
          return (
            <li key={path.path_id} className="academy-path">
              <div className="flex items-start justify-between gap-sm">
                <h2 className="text-md font-semibold text-primary">{path.title}</h2>
                {certified ? (
                  <span className="academy-badge" data-state="certified">
                    certified
                  </span>
                ) : null}
              </div>
              <p className="mt-3xs text-2xs uppercase tracking-wide text-muted">
                {path.persona.replace(/_/g, ' ')} ·{' '}
                {count(path.estimated_minutes, 'minute', 'minutes')}
              </p>
              <p className="mt-2xs text-sm text-secondary">{path.summary}</p>

              {state && state.total > 0 ? (
                <p className="mt-2xs text-2xs text-muted tabular-nums">
                  {state.completed} of {state.total} modules passed
                </p>
              ) : null}

              <ol className="academy-modules">
                {path.modules.map((module) => (
                  <li key={module.module_id}>
                    <Link
                      href={`/academy/${module.module_id}`}
                      className="academy-module"
                      data-passed={state?.completed_module_ids.includes(module.module_id)}
                    >
                      <span>{module.title}</span>
                      <span className="academy-minutes tabular-nums">
                        {module.estimated_minutes}m
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>

              <p className="academy-cert">
                Grants <strong className="font-medium">{path.certification_code}</strong>
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
