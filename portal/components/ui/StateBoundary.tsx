import type { ReactNode } from 'react';

import type { Tab, TabState } from '@/lib/types';

/**
 * Every component ships five states (BUILD.md section 12): loading, empty,
 * error, partial-permission and populated. This renders four of them from a
 * tab payload; loading is the Suspense fallback the caller supplies.
 *
 * The rule the empty state follows is that it is never a dead end: it says what
 * would produce the content, so a reader can tell a gap in the estate from a
 * gap in the page.
 */
export function StateBoundary({
  tab,
  children,
  emptyTitle,
}: {
  tab: Pick<Tab<unknown>, 'state' | 'why' | 'required_scope' | 'request_access_url'>;
  children: ReactNode;
  emptyTitle: string;
}) {
  if (tab.state === 'empty') {
    return (
      <div className="rounded-lg border border-subtle bg-sunken p-lg">
        <p className="text-sm font-medium text-primary">{emptyTitle}</p>
        {tab.why ? <p className="mt-2xs text-sm text-secondary">{tab.why}</p> : null}
      </div>
    );
  }

  return (
    <div>
      {tab.state === 'partial_permission' && tab.required_scope ? (
        <PermissionNotice scope={tab.required_scope} href={tab.request_access_url} why={tab.why} />
      ) : null}
      {tab.state === 'partial' && tab.why ? (
        <p className="mb-md rounded-md border border-subtle bg-sunken px-md py-sm text-sm text-secondary">
          {tab.why}
        </p>
      ) : null}
      {children}
    </div>
  );
}

export function PermissionNotice({
  scope,
  href,
  why,
}: {
  scope: string;
  href?: string;
  why?: string;
}) {
  return (
    <div className="mb-md rounded-md border border-strong bg-sunken px-md py-sm">
      <p className="text-sm text-primary">
        {why ?? 'Some of this needs an entitlement you do not hold yet.'}
      </p>
      <p className="mt-2xs text-xs text-secondary">
        Missing scope <code className="font-mono">{scope}</code>
      </p>
      {href ? (
        <a
          className="mt-xs inline-block rounded-md bg-accent px-md py-2xs text-xs font-medium text-on-hero"
          href={href}
        >
          Request access
        </a>
      ) : null}
    </div>
  );
}

export function ErrorState({ detail, title }: { detail: string; title: string }) {
  return (
    <div role="alert" className="rounded-lg border border-strong bg-sunken p-lg">
      <p className="text-sm font-medium text-status-error">{title}</p>
      <p className="mt-2xs text-sm text-secondary">{detail}</p>
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-subtle bg-sunken p-lg" aria-busy="true">
      <p className="text-sm text-secondary">{label}</p>
    </div>
  );
}

export const TAB_STATE_LABEL: Record<TabState, string> = {
  populated: 'Complete',
  partial: 'Partial',
  partial_permission: 'Access required',
  empty: 'Not yet available',
};
