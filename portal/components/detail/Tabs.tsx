import Link from 'next/link';

import { cn } from '@/lib/cn';
import type { Tab } from '@/lib/types';

/**
 * The detail tab bar.
 *
 * Tabs are links, not buttons: each tab is a URL, so a reader can share "the
 * contract tab of this product" and a screen-reader user gets ordinary
 * navigation semantics rather than a widget to learn.
 *
 * A tab whose state is not `populated` says so in the bar itself, so nobody
 * clicks through four tabs to discover which ones have anything in them.
 */
export interface TabDefinition {
  code: string;
  label: string;
}

export function TabBar({
  tabs,
  states,
  active,
  basePath,
}: {
  tabs: TabDefinition[];
  states: Record<string, Pick<Tab<unknown>, 'state'>>;
  active: string;
  basePath: string;
}) {
  return (
    <nav aria-label="Sections" className="border-b border-subtle">
      <ul role="list" className="flex flex-wrap gap-3xs">
        {tabs.map((tab) => {
          const state = states[tab.code]?.state ?? 'empty';
          const isActive = tab.code === active;
          return (
            <li key={tab.code}>
              <Link
                href={tab.code === 'overview' ? basePath : `${basePath}?tab=${tab.code}`}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'inline-flex items-center gap-2xs border-b-2 px-md py-sm text-sm transition-colors duration-micro ease-standard',
                  isActive
                    ? 'border-accent font-medium text-primary'
                    : 'border-transparent text-secondary hover:text-primary',
                )}
              >
                {tab.label}
                {state !== 'populated' ? (
                  <span
                    className={cn(
                      'rounded-pill px-2xs py-3xs text-2xs uppercase tracking-wide',
                      state === 'partial_permission'
                        ? 'text-band-watch'
                        : state === 'partial'
                          ? 'text-band-healthy'
                          : 'text-muted',
                    )}
                  >
                    {state === 'partial_permission'
                      ? 'access'
                      : state === 'partial'
                        ? 'partial'
                        : 'empty'}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
