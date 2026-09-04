import Link from 'next/link';

import type { MeshTableRow } from '@/lib/types';

/**
 * The table equivalent every mesh view has (M9.4).
 *
 * Not a fallback and not an accessibility afterthought — it is the same payload
 * the graph is drawn from, rendered in the order the graph ranks it, and it is
 * on the page at the same time. A graph is a good way to see shape and a bad
 * way to read a number, and forcing a keyboard user through a canvas to reach a
 * figure that is right there in a row helps nobody.
 *
 * Every row carries its rationale, because I6 says an edge nobody can explain
 * is not rendered — and an unexplained row is as unrenderable as an unexplained
 * line.
 */
export function MeshTable({
  rows,
  hrefBase,
  caption,
}: {
  rows: MeshTableRow[];
  hrefBase: string;
  caption: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
        No edge clears the render threshold in this view. That is a claim about the
        estate, not a gap in the page: nothing here is related strongly enough to draw.
      </p>
    );
  }

  return (
    <div className="answer-table-wrap">
      <table className="answer-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">From</th>
            <th scope="col">To</th>
            <th scope="col">Relationship</th>
            <th scope="col">Strength</th>
            <th scope="col">Confidence</th>
            <th scope="col">Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.source}-${row.target}-${row.edge_type}`}>
              <td>
                <Link href={`${hrefBase}/${row.source}`} className="hover:underline">
                  {row.source_name}
                </Link>
              </td>
              <td>
                <Link href={`${hrefBase}/${row.target}`} className="hover:underline">
                  {row.target_name}
                </Link>
              </td>
              <td>{row.edge_type.replace(/_/g, ' ')}</td>
              <td className="tabular-nums">{row.strength}</td>
              <td className="tabular-nums">{row.confidence}</td>
              <td>{row.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
