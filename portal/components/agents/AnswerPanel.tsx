import { Badge } from '@/components/ui/Badge';
import type { AgentAnswer } from '@/lib/types';

/**
 * The answer itself: headline, visual, table, and the citation chips.
 *
 * The tier badge is on the answer, not on the page, because a consumer reads
 * the answer and looks away. A page-level badge is a badge on a container the
 * reader has already stopped looking at.
 *
 * The visual is drawn as bars from the table's own rows rather than by a chart
 * library. That keeps the motion budget (13.6) reachable — the only animated
 * properties are transform and opacity — and it keeps the numbers on screen
 * identical to the numbers in the table, because they are the same numbers.
 */
export function AnswerPanel({ answer }: { answer: AgentAnswer }) {
  const { answer: body, citations, kpi_definitions: kpis, notes, tier } = answer;
  const values = body.table.rows.map((row) => Number(row[1] ?? 0));
  const peak = Math.max(...values.map(Math.abs), 1);

  return (
    <article className="answer-panel">
      <header className="flex flex-wrap items-start justify-between gap-sm">
        <h2 className="max-w-2xl text-lg font-semibold leading-snug text-primary">
          {body.headline}
        </h2>
        <Badge tone="neutral" code={tier} title={`Answered against the ${tier} tier`}>
          {tier} tier
        </Badge>
      </header>

      <p className="mt-sm max-w-2xl text-sm text-secondary">{body.narrative}</p>

      {notes.length > 0 ? (
        <ul className="mt-sm space-y-3xs">
          {notes.map((note) => (
            <li key={note} className="text-2xs text-band-watch">
              {note}
            </li>
          ))}
        </ul>
      ) : null}

      {body.table.rows.length > 0 ? (
        <figure className="answer-visual" aria-label={`${body.visual.type} of ${body.table.columns[1]}`}>
          <ul className="answer-bars">
            {body.table.rows.map((row, index) => (
              <li key={String(row[0])} className="answer-bar-row">
                <span className="answer-bar-label" title={String(row[0])}>
                  {String(row[0])}
                </span>
                <span className="answer-bar-track">
                  <span
                    className="answer-bar-fill"
                    style={{
                      transform: `scaleX(${Math.abs(Number(row[1] ?? 0)) / peak})`,
                      transitionDelay: `${index * 24}ms`,
                    }}
                  />
                </span>
                <span className="answer-bar-value">
                  {row[1] === null ? '—' : Number(row[1]).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </figure>
      ) : null}

      <div className="answer-table-wrap">
        <table className="answer-table">
          <caption className="sr-only">
            {body.headline} — full result, {body.table.rows.length} rows
          </caption>
          <thead>
            <tr>
              {body.table.columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.table.rows.map((row) => (
              <tr key={String(row[0])}>
                {row.map((cell, index) => (
                  <td key={index} className={index === 0 ? '' : 'tabular-nums'}>
                    {cell === null ? '—' : typeof cell === 'number' ? cell.toLocaleString() : cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="answer-citations">
        <span className="text-2xs uppercase tracking-wide text-muted">Grounded in</span>
        <ul className="trace-chips">
          {citations.map((citation) => (
            <li key={citation.product_id} className="trace-chip">
              {citation.product_id} v{citation.contract_version}
              {citation.as_of ? ` · ${citation.as_of.slice(0, 10)}` : ''}
            </li>
          ))}
          {kpis.map((kpi) => (
            <li key={kpi} className="trace-chip font-mono">
              {kpi}
            </li>
          ))}
        </ul>
      </footer>
    </article>
  );
}
