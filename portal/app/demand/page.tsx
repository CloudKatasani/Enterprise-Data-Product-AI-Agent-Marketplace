import Link from 'next/link';

import { apiTry } from '@/lib/api';
import type { DemandItem, DemandTheme } from '@/lib/types';

export const dynamic = 'force-dynamic';

interface Board {
  items: DemandItem[];
  themes: DemandTheme[];
}

/**
 * The public demand board (section 14.3).
 *
 * Public because a demand board only works if the people who filed things can
 * see what happened to them. Votes carry the use case that justified them, and
 * themes carry the number of distinct teams behind them — a theme with five is
 * escalated, and the board says so rather than leaving it to be noticed.
 */
export default async function DemandPage() {
  const result = await apiTry<Board>('/demand');

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <p className="text-sm text-secondary">{result.problem.detail}</p>
      </div>
    );
  }

  const { items, themes } = result.data;

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 className="text-xl font-semibold text-primary">Demand</h1>
          <p className="mt-3xs text-sm text-secondary">
            What the estate has been asked for and has not built yet. Everything here is
            public, including what was declined and why.
          </p>
        </div>
        <Link href="/requests/new/supply" className="refusal-action">
          File demand
        </Link>
      </header>

      {themes.length > 0 ? (
        <section className="mb-xl">
          <h2 className="refusal-subhead">Themes</h2>
          <ul className="mt-2xs grid grid-cols-1 gap-2xs sm:grid-cols-2 xl:grid-cols-3">
            {themes.map((theme) => (
              <li key={theme.theme_id} className="rounded-md border border-subtle p-md">
                <div className="flex items-baseline justify-between gap-2xs">
                  <h3 className="text-sm font-medium text-primary">{theme.label}</h3>
                  {theme.escalated_at ? (
                    <span className="text-2xs text-band-watch">escalated</span>
                  ) : null}
                </div>
                <p className="mt-3xs text-2xs text-muted">{theme.summary}</p>
                <p className="mt-2xs text-2xs text-secondary">
                  {theme.distinct_team_count} team
                  {theme.distinct_team_count === 1 ? '' : 's'} · confidence{' '}
                  {theme.confidence}
                </p>
                <p className="mt-3xs text-2xs text-muted">{theme.rationale}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h2 className="refusal-subhead">Requests</h2>
        {items.length === 0 ? (
          <p className="mt-2xs rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
            Nothing has been asked for yet. That is not necessarily good news — an empty
            demand board more often means people have stopped asking than that everything
            exists.
          </p>
        ) : (
          <ul className="mt-2xs space-y-2xs">
            {items.map((item) => (
              <li key={item.demand_id} className="rounded-md border border-subtle p-md">
                <div className="flex flex-wrap items-baseline justify-between gap-2xs">
                  <h3 className="text-sm font-medium text-primary">{item.title}</h3>
                  <span className="text-2xs tabular-nums text-muted">
                    {item.votes} vote{item.votes === 1 ? '' : 's'} from {item.teams} team
                    {item.teams === 1 ? '' : 's'}
                    {item.score === null ? '' : ` · score ${item.score}`}
                  </span>
                </div>
                <p className="mt-2xs text-sm text-secondary">{item.body}</p>
                <p className="mt-2xs text-2xs text-muted">
                  {item.state.replace(/_/g, ' ')}
                  {item.decline_reason_public
                    ? ` — ${item.decline_reason_public}`
                    : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
