import Link from 'next/link';

import { apiTry } from '@/lib/api';
import type { AcademyModule } from '@/lib/types';
import { count } from '@/lib/units';

/**
 * The contextual runbook (M12.1; specification 20.2).
 *
 * The right module, one click from the listing that raised the question. That
 * is the whole idea: a consumer who cannot tell whether a quality score of 87
 * is good should not have to find the academy, choose a path and scan six
 * modules — the answer belongs on the page where the question occurred to them.
 *
 * Scoped to the asset class rather than the whole academy. A link that opens
 * eleven modules has not answered anything; it has handed over a reading list.
 *
 * The band is omitted rather than shown empty when there is nothing to link to.
 * A heading over a blank space costs a reader the moment it takes to work out
 * that there is nothing behind it.
 */
export async function ContextualRunbook({
  assetType,
  assetId,
}: {
  assetType: 'data_product' | 'agent';
  assetId: string;
}) {
  const result = await apiTry<{ modules: AcademyModule[] }>('/academy/contextual', {
    asset_type: assetType,
    asset_id: assetId,
  });
  if (!result.ok || result.data.modules.length === 0) return null;

  const modules = result.data.modules;
  const minutes = modules.reduce((total, module) => total + module.estimated_minutes, 0);

  return (
    <aside className="runbook" aria-labelledby="runbook-heading">
      <h2 id="runbook-heading" className="refusal-subhead">
        How to use this
      </h2>
      <p className="mt-2xs text-sm text-secondary">
        {count(minutes, 'minute', 'minutes')} of it, and every module runs against the
        demo tier so you write a real query rather than read about one.
      </p>
      <ol className="runbook-list">
        {modules.map((entry) => (
          <li key={entry.module_id}>
            <Link href={`/academy/${entry.module_id}`} className="runbook-module">
              <span>{entry.title}</span>
              <span className="academy-minutes tabular-nums">
                {entry.estimated_minutes}m
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </aside>
  );
}
