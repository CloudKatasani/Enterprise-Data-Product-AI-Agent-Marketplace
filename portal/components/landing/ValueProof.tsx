import type { ProofTile } from '@/lib/types';

/**
 * The value-proof tiles (band 9).
 *
 * Three numbers this system already computes for its own consoles. Each one
 * states its window and where it came from, because a quantified claim without
 * its method is a number somebody chose. A tile with nothing behind it is
 * omitted by the API rather than shown at zero — an estate that has not yet
 * deflected an analyst hour should not present a zero as an achievement.
 */
export function ValueProof({ tiles }: { tiles: ProofTile[] }) {
  if (tiles.length === 0) return null;

  return (
    <section className="proof" aria-labelledby="proof-heading">
      <h2 id="proof-heading" className="band-heading">
        What it has been worth
      </h2>
      <ul className="proof-grid" role="list">
        {tiles.map((tile) => (
          <li key={tile.code} className="proof-tile">
            <p className="proof-value tabular-nums">
              {tile.value.toLocaleString()}{' '}
              <span className="proof-unit">{tile.unit}</span>
            </p>
            <p className="proof-label">{tile.label}</p>
            <p className="proof-detail">{tile.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
