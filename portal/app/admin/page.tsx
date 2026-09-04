import Link from 'next/link';

import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import { FORBIDDEN } from '@/lib/http-status';
import type {
  ConnectorRow,
  FeatureFlagRow,
  RubricSummary,
  TaxonomyPanel,
  TenancyPanel,
} from '@/lib/types';
import { count } from '@/lib/units';

export const dynamic = 'force-dynamic';

const TABS = [
  { code: 'rubrics', label: 'Rubrics' },
  { code: 'taxonomies', label: 'Taxonomies' },
  { code: 'connectors', label: 'Connectors' },
  { code: 'flags', label: 'Flags' },
  { code: 'tenancy', label: 'Tenancy' },
] as const;

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * The admin console (M12.2).
 *
 * What it can do is bounded on purpose. It publishes new rubric versions and
 * toggles flags; it cannot edit a version that exists, an audit event, a
 * snapshot or a grant, because those are append-only at the database and no
 * console talks its way past a trigger. An administrator has wide authority
 * over what the rules are and none at all over what happened, and an estate
 * where those are one permission cannot be audited.
 *
 * Every panel shows what depends on the thing it configures: how many snapshots
 * a superseded rubric version is still explaining, how many products a taxonomy
 * code is holding up, how old a flag is. Configuration without its dependants
 * is an invitation to change something on the assumption that nothing was using
 * it.
 */
export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const tab = typeof params.tab === 'string' ? params.tab : TABS[0].code;

  const [rubrics, taxonomies, connectors, flags, tenancy] = await Promise.all([
    apiTry<{ rubrics: RubricSummary[] }>('/admin/rubrics'),
    apiTry<{ taxonomies: TaxonomyPanel[] }>('/admin/taxonomies'),
    apiTry<{ connectors: ConnectorRow[] }>('/admin/connectors'),
    apiTry<{ flags: FeatureFlagRow[] }>('/admin/flags'),
    apiTry<TenancyPanel>('/admin/tenancy'),
  ]);

  if (!rubrics.ok && rubrics.problem.status === FORBIDDEN) {
    return (
      <PageMessage title="Administration">
        {rubrics.problem.detail} No grant carries an administrator role, so there is
        nothing to request here — this console is opened by role assignment.
      </PageMessage>
    );
  }

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg max-w-prose">
        <h1 className="text-xl font-semibold text-primary">Administration</h1>
        <p className="mt-3xs text-sm text-secondary">
          What the rules are, and what currently depends on them. Publishing a rubric
          version re-scores the estate and leaves every prior snapshot exactly where it
          was, so a weight change is visible as a change rather than as a new past.
        </p>
      </header>

      <nav aria-label="Administration sections" className="border-b border-subtle">
        <ul className="flex flex-wrap gap-3xs">
          {TABS.map((entry) => (
            <li key={entry.code}>
              <Link
                href={`/admin?tab=${entry.code}`}
                aria-current={entry.code === tab ? 'page' : undefined}
                className="inline-flex border-b-2 border-transparent px-md py-sm text-sm text-secondary aria-[current]:border-accent aria-[current]:text-accent"
              >
                {entry.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-lg">
        {tab === 'rubrics' ? <Rubrics rows={rubrics.ok ? rubrics.data.rubrics : []} /> : null}
        {tab === 'taxonomies' ? (
          <Taxonomies panels={taxonomies.ok ? taxonomies.data.taxonomies : []} />
        ) : null}
        {tab === 'connectors' ? (
          <Connectors rows={connectors.ok ? connectors.data.connectors : []} />
        ) : null}
        {tab === 'flags' ? <Flags rows={flags.ok ? flags.data.flags : []} /> : null}
        {tab === 'tenancy' ? <Tenancy panel={tenancy.ok ? tenancy.data : null} /> : null}
      </div>
    </div>
  );
}

function Rubrics({ rows }: { rows: RubricSummary[] }) {
  return (
    <section>
      <h2 className="refusal-subhead">Rubrics in force</h2>
      <p className="mt-2xs mb-md max-w-prose text-sm text-secondary">
        Every weight, threshold, band and target this system decides on. A change is a
        new version: the one it replaces is superseded rather than edited, and every
        score already recorded keeps pointing at the version it was computed under.
      </p>
      <div className="answer-table-wrap">
        <table className="answer-table">
          <caption className="sr-only">Rubrics and the versions in force</caption>
          <thead>
            <tr>
              <th scope="col">Rubric</th>
              <th scope="col">Version</th>
              <th scope="col">Criteria</th>
              <th scope="col">Versions</th>
              <th scope="col">In force since</th>
              <th scope="col">Published by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.code}>
                <td>
                  <Link href={`/admin/rubrics/${row.code}`} className="hover:underline">
                    {row.code}
                  </Link>
                </td>
                <td className="tabular-nums">{row.semver ?? '—'}</td>
                <td className="tabular-nums">{row.criteria}</td>
                <td className="tabular-nums">{row.versions}</td>
                <td>{row.effective_from?.split('T')[0] ?? '—'}</td>
                <td>{row.created_by ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Taxonomies({ panels }: { panels: TaxonomyPanel[] }) {
  return (
    <div className="space-y-xl">
      <p className="max-w-prose text-sm text-secondary">
        Controlled vocabulary, and what is standing on each code. An entry with products
        behind it is not a row to retire quietly.
      </p>
      {panels.map((panel) => (
        <section key={panel.taxonomy}>
          <h2 className="refusal-subhead">{panel.taxonomy.replace(/_/g, ' ')}</h2>
          <ul className="taxonomy-strip mt-2xs" role="list">
            {panel.entries.map((entry) => (
              <li key={entry.code} className="taxonomy-chip">
                <span className="taxonomy-label">{entry.label}</span>
                <span className="taxonomy-uses tabular-nums">{entry.uses}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Connectors({ rows }: { rows: ConnectorRow[] }) {
  return (
    <section>
      <h2 className="refusal-subhead">Source systems</h2>
      <p className="mt-2xs mb-md max-w-prose text-sm text-secondary">
        Every connector service principal is read-only. That is not reported from
        configuration here — <code className="module-code">npm run test:kill</code>{' '}
        attempts a write on every supported platform on every build and requires all of
        them to fail. A flag called <em>read only</em> would only report an intention.
      </p>
      <div className="answer-table-wrap">
        <table className="answer-table">
          <caption className="sr-only">Source systems and what they feed</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Platform</th>
              <th scope="col">Owner</th>
              <th scope="col">Criticality</th>
              <th scope="col">Products fed</th>
              <th scope="col">Last harvested</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.source_id}>
                <td>{row.name}</td>
                <td>{row.platform}</td>
                <td>{row.owner_team}</td>
                <td>{row.criticality}</td>
                <td className="tabular-nums">{row.products}</td>
                <td>{row.last_harvest?.split('T')[0] ?? 'never'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Flags({ rows }: { rows: FeatureFlagRow[] }) {
  return (
    <section>
      <h2 className="refusal-subhead">Feature flags</h2>
      <p className="mt-2xs mb-md max-w-prose text-sm text-secondary">
        Only flags something actually branches on. A console listing switches that do
        nothing is worse than no console: it invites someone to turn one off during an
        incident and conclude the problem is elsewhere when nothing changes.
      </p>
      <ul className="space-y-2xs" role="list">
        {rows.map((row) => (
          <li key={row.code} className="flag-row" data-expired={row.expired}>
            <div className="flex items-start justify-between gap-md">
              <div>
                <p className="text-sm font-medium text-primary">{row.code}</p>
                <p className="mt-3xs max-w-prose text-sm text-secondary">
                  {row.description}
                </p>
              </div>
              <span className="flag-state" data-enabled={row.enabled}>
                {row.enabled ? 'on' : 'off'}
              </span>
            </div>
            <p className="mt-2xs text-2xs text-muted">
              {row.flag_type} · owner {row.owner_party_id ?? 'unassigned'} ·{' '}
              {count(row.age_days, 'day', 'days')} old
              {row.expires_at
                ? ` · expires ${row.expires_at.split('T')[0]}`
                : ' · no expiry set'}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Tenancy({ panel }: { panel: TenancyPanel | null }) {
  if (panel === null) {
    return <p className="text-sm text-secondary">The tenancy panel is unavailable.</p>;
  }
  return (
    <div className="space-y-xl">
      <section>
        <h2 className="refusal-subhead">Isolation</h2>
        <p className="mt-2xs max-w-prose text-sm text-secondary">
          A table needs row-level security exactly when it carries a tenant. That is read
          from the schema rather than from a list somebody maintains, because a
          hand-written exception list eventually contains a table that should not be on
          it.
        </p>
        <dl className="tenancy-stats">
          <div>
            <dt>Tables</dt>
            <dd className="tabular-nums">{panel.tables}</dd>
          </div>
          <div>
            <dt>Tenant-scoped</dt>
            <dd className="tabular-nums">{panel.tenanted_tables}</dd>
          </div>
          <div>
            <dt>With forced RLS</dt>
            <dd className="tabular-nums">{panel.row_level_security}</dd>
          </div>
          <div>
            <dt>Shared vocabulary</dt>
            <dd className="tabular-nums">{panel.shared_reference_tables.length}</dd>
          </div>
        </dl>
        {panel.unprotected_tables.length > 0 ? (
          <p className="mt-md rounded-md border border-subtle p-md text-sm text-secondary">
            <strong className="font-medium">
              {count(panel.unprotected_tables.length, 'table carries', 'tables carry')} a
              tenant and no forced policy:
            </strong>{' '}
            {panel.unprotected_tables.join(', ')}. Each one is a cross-tenant read waiting
            to happen.
          </p>
        ) : (
          <p className="mt-md text-sm text-secondary">
            Every tenant-scoped table forces its isolation policy.
          </p>
        )}
      </section>

      <section>
        <h2 className="refusal-subhead">Organisation</h2>
        <ul className="mt-2xs space-y-3xs text-sm text-secondary" role="list">
          {panel.org_units.map((unit) => (
            <li key={unit.org_unit_id}>
              {unit.name}
              {unit.region ? ` · ${unit.region}` : ''}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
