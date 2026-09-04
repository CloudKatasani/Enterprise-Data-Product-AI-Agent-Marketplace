import Link from 'next/link';

import type { Facet } from '@/lib/types';

/**
 * The facet rail.
 *
 * Counts reflect every *other* selection but not the facet's own, so choosing
 * an industry never collapses the industry list and the consumer can always
 * change their mind. Each value is a link rather than a control, so the whole
 * rail works without JavaScript and every state is addressable.
 */
export function FacetRail({
  facets,
  selected,
  basePath,
}: {
  facets: Facet[];
  selected: Record<string, string[]>;
  basePath: string;
}) {
  return (
    <nav aria-label="Filters" className="space-y-lg">
      {facets
        .filter((facet) => facet.values.length > 0)
        .map((facet) => (
          <section key={facet.code}>
            <h2 className="text-2xs font-semibold uppercase tracking-wide text-muted">
              {facet.label}
            </h2>
            <ul className="mt-xs space-y-3xs">
              {facet.values.map((value) => {
                const href = toggleHref(basePath, selected, facet.code, value.value);
                return (
                  <li key={value.value}>
                    <Link
                      href={href}
                      aria-current={value.selected ? 'true' : undefined}
                      className={
                        value.selected
                          ? 'flex items-center justify-between gap-xs rounded-md bg-sunken px-xs py-3xs text-sm font-medium text-primary'
                          : 'flex items-center justify-between gap-xs rounded-md px-xs py-3xs text-sm text-secondary hover:bg-sunken hover:text-primary'
                      }
                    >
                      <span className="truncate">{value.value.replace(/_/g, ' ')}</span>
                      <span className="text-2xs tabular-nums text-muted">{value.count}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
    </nav>
  );
}

function toggleHref(
  basePath: string,
  selected: Record<string, string[]>,
  code: string,
  value: string,
): string {
  const next: Record<string, string[]> = { ...selected };
  const current = next[code] ?? [];
  next[code] = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];

  const params = new URLSearchParams();
  for (const [key, values] of Object.entries(next)) {
    for (const item of values) params.append(key, item);
  }
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}
