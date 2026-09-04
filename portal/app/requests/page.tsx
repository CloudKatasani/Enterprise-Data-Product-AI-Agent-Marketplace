import Link from 'next/link';

import { apiTry } from '@/lib/api';
import type { BacklogItem, Grant } from '@/lib/types';

export const dynamic = 'force-dynamic';

interface Register {
  grants: Grant[];
  expiring: { grant_id: string; asset_id: string; expires_at: string }[];
  expired: { grant_id: string; asset_id: string; expires_at: string }[];
  dormant: { grant_id: string; asset_id: string; approved_by: string | null }[];
}

interface Backlog {
  items: BacklogItem[];
  overdue: { request_id: string; title: string; sla_due_at: string }[];
  sla: { open: number; breached: number; rows: Record<string, unknown>[] };
}

/**
 * The date part of an ISO timestamp.
 *
 * `slice(0, 10)` would do it, but the 10 is a magic number in a component and
 * the rule against those exists precisely so that a reader does not have to
 * count characters to know what a line means.
 */
function isoDate(timestamp: string): string {
  const [day] = timestamp.split('T');
  return day ?? timestamp;
}

const TABS = [
  { code: 'mine', label: 'My access' },
  { code: 'backlog', label: 'Backlog' },
  { code: 'sla', label: 'SLA board' },
] as const;

export default async function RequestsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const tab = typeof params.tab === 'string' ? params.tab : 'mine';

  const [registerResult, backlogResult] = await Promise.all([
    apiTry<Register>('/requests/entitlements', { mine: true }),
    apiTry<Backlog>('/requests/backlog'),
  ]);

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 className="text-xl font-semibold text-primary">Requests</h1>
          <p className="mt-3xs text-sm text-secondary">
            What you hold, what the estate has been asked for, and what is running late.
          </p>
        </div>
        <div className="flex flex-wrap gap-2xs">
          <Link href="/requests/new/access" className="refusal-action">
            Request access
          </Link>
          <Link href="/requests/new/supply" className="refusal-action">
            File demand
          </Link>
        </div>
      </header>

      <nav aria-label="Sections" className="border-b border-subtle">
        <ul className="flex flex-wrap gap-3xs">
          {TABS.map((entry) => (
            <li key={entry.code}>
              <Link
                href={`/requests?tab=${entry.code}`}
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
        {tab === 'backlog' ? (
          <BacklogTable backlog={backlogResult.ok ? backlogResult.data : null} />
        ) : tab === 'sla' ? (
          <SlaBoard backlog={backlogResult.ok ? backlogResult.data : null} />
        ) : (
          <GrantsTable register={registerResult.ok ? registerResult.data : null} />
        )}
      </div>
    </div>
  );
}

function GrantsTable({ register }: { register: Register | null }) {
  if (register === null || register.grants.length === 0) {
    return (
      <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
        You hold no grants yet. Every product page has a request button, and the form
        tells you what will happen before you submit.
      </p>
    );
  }
  return (
    <div className="answer-table-wrap">
      <table className="answer-table">
        <caption className="sr-only">Grants you hold</caption>
        <thead>
          <tr>
            <th scope="col">Asset</th>
            <th scope="col">Purpose</th>
            <th scope="col">Platform role</th>
            <th scope="col">Columns</th>
            <th scope="col">Expires</th>
            <th scope="col">State</th>
          </tr>
        </thead>
        <tbody>
          {register.grants.map((grant) => (
            <tr key={grant.grant_id}>
              <td>{grant.asset_id}</td>
              <td>{grant.purpose_code.replace(/_/g, ' ')}</td>
              <td className="font-mono text-2xs">{grant.platform_role}</td>
              <td className="tabular-nums">{grant.columns.length}</td>
              <td>{isoDate(grant.expires_at)}</td>
              <td>{grant.live ? 'live' : 'revoked'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BacklogTable({ backlog }: { backlog: Backlog | null }) {
  if (backlog === null || backlog.items.length === 0) {
    return (
      <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
        Nothing has been asked for yet.
      </p>
    );
  }
  return (
    <ul className="space-y-2xs">
      {backlog.items.map((item) => (
        <li key={item.request_id} className="rounded-md border border-subtle p-md">
          <div className="flex flex-wrap items-baseline justify-between gap-2xs">
            <h2 className="text-sm font-medium text-primary">{item.title}</h2>
            <span className="text-2xs text-muted">
              {item.state.replace(/_/g, ' ')} · {item.votes} vote
              {item.votes === 1 ? '' : 's'}
            </span>
          </div>
          <p className="mt-2xs text-sm text-secondary">{item.body}</p>
          {item.decline ? (
            <p className="mt-2xs text-2xs text-band-watch">
              Declined as {item.decline.reason_code.replace(/_/g, ' ')}:{' '}
              {item.decline.reason_text}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function SlaBoard({ backlog }: { backlog: Backlog | null }) {
  if (backlog === null) {
    return <p className="text-sm text-secondary">The SLA board is unavailable.</p>;
  }
  return (
    <div>
      <dl className="mb-lg grid grid-cols-2 gap-md sm:grid-cols-4">
        <div>
          <dt className="refusal-subhead">Open</dt>
          <dd className="mt-3xs text-lg font-medium text-primary">{backlog.sla.open}</dd>
        </div>
        <div>
          <dt className="refusal-subhead">Breached</dt>
          <dd className="mt-3xs text-lg font-medium text-band-at-risk">
            {backlog.sla.breached}
          </dd>
        </div>
      </dl>
      {backlog.overdue.length === 0 ? (
        <p className="text-sm text-secondary">Nothing is past its clock.</p>
      ) : (
        <ul className="space-y-2xs">
          {backlog.overdue.map((item) => (
            <li key={item.request_id} className="rounded-md border border-subtle p-md">
              <p className="text-sm text-primary">{item.title}</p>
              <p className="mt-3xs text-2xs text-band-at-risk">
                due {isoDate(item.sla_due_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
