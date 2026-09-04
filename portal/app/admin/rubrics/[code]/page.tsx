import Link from 'next/link';

import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { RubricVersionRow } from '@/lib/types';
import { count } from '@/lib/units';

export const dynamic = 'force-dynamic';

/** JSON indentation. Written as the string it is, so no literal is needed. */
const INDENT = '  ';

interface RubricDetail {
  code: string;
  payload: Record<string, unknown>;
  versions: RubricVersionRow[];
}

/**
 * One rubric: what it currently says, and every version it has ever said it in.
 *
 * The version history is the point of the page. A superseded version with
 * snapshots behind it is not dead weight — it is what makes those scores
 * replayable, and the count is shown beside it so nobody proposes cleaning it
 * up. Nothing on this page can delete one.
 *
 * The payload is shown rather than edited inline. Publishing goes through
 * `POST /admin/rubrics/{code}/versions`, which refuses a content change that
 * did not move the declared version — the same rule the seeder enforces, for
 * the same reason: two different rubrics answering to one version name makes
 * every score computed under that name unreplayable.
 */
export default async function RubricPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  const result = await apiTry<RubricDetail>(`/admin/rubrics/${code}`);

  if (!result.ok) {
    return <PageMessage title="Rubric">{result.problem.detail}</PageMessage>;
  }

  const { payload, versions } = result.data;
  const inForce = versions.find((version) => version.in_force);

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <nav aria-label="Breadcrumb" className="mb-md text-2xs text-muted">
        <Link href="/admin?tab=rubrics" className="hover:underline">
          Administration
        </Link>
        {' · rubrics'}
      </nav>

      <header className="mb-lg max-w-prose">
        <h1 className="text-xl font-semibold text-primary">{code}</h1>
        <p className="mt-3xs text-sm text-secondary">
          Version {inForce?.semver ?? 'unknown'} is in force, published by{' '}
          {inForce?.created_by ?? 'unknown'}. Publishing a change writes a new version and
          supersedes this one; it does not edit it.
        </p>
      </header>

      <div className="admin-columns">
        <section>
          <h2 className="refusal-subhead">What it says</h2>
          <pre className="rubric-payload">{JSON.stringify(payload, null, INDENT)}</pre>
        </section>

        <section>
          <h2 className="refusal-subhead">Every version</h2>
          <ul className="mt-2xs space-y-2xs" role="list">
            {versions.map((version) => (
              <li
                key={version.rubric_version_id}
                className="version-row"
                data-in-force={version.in_force}
              >
                <div className="flex items-baseline justify-between gap-sm">
                  <p className="text-sm font-medium text-primary tabular-nums">
                    {version.semver}
                  </p>
                  <p className="text-2xs text-muted">
                    {version.in_force ? 'in force' : 'superseded'}
                  </p>
                </div>
                <p className="mt-3xs text-2xs text-muted">
                  {version.source_hash} · {version.effective_from.split('T')[0]} ·{' '}
                  {version.created_by}
                </p>
                {version.quality_snapshots > 0 ? (
                  <p className="mt-3xs text-2xs text-secondary">
                    Still explaining{' '}
                    {count(version.quality_snapshots, 'score', 'scores')}. That is why it
                    is kept.
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
