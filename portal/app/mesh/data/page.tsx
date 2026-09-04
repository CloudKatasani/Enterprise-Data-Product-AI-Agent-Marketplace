import Link from 'next/link';

import { MeshDiagram, type SvgLayout } from '@/components/mesh/MeshDiagram';
import { MeshTable } from '@/components/mesh/MeshTable';
import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { BlastRadius, MeshGraph } from '@/lib/types';

export const dynamic = 'force-dynamic';

const MODES = [
  { code: 'force', label: 'All relationships', hint: 'Every edge above the render threshold.' },
  { code: 'domain', label: 'By domain', hint: 'One domain at a time, and what links inside it.' },
  { code: 'source', label: 'Source-anchored', hint: 'Pick a source system; see what depends on it.' },
  { code: 'duplication', label: 'Possible duplication', hint: 'Pairs alike on both sources and purpose.' },
  { code: 'gap', label: 'Demand gaps', hint: 'Where people are asking and nothing is published.' },
] as const;

interface SourceList {
  sources: { source_id: string; name: string; platform: string; criticality: string;
             downstream_products: number }[];
}

export default async function DataMeshPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const mode = typeof params.mode === 'string' ? params.mode : 'force';
  const domain = typeof params.domain === 'string' ? params.domain : undefined;
  const source = typeof params.source === 'string' ? params.source : undefined;

  const [graphResult, sourcesResult, blastResult] = await Promise.all([
    apiTry<MeshGraph>('/mesh/data', { mode: mode === 'source' ? 'force' : mode, domain }),
    apiTry<SourceList>('/mesh/sources'),
    source
      ? apiTry<BlastRadius>('/mesh/data/blast-radius', { source })
      : Promise.resolve(null),
  ]);

  if (!graphResult.ok) {
    return <PageMessage title="The mesh is unavailable">{graphResult.problem.detail}</PageMessage>;
  }

  const graph = graphResult.data;
  const domains = [...new Set(graph.nodes.map((node) => node.domain))].sort();

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg">
        <h1 className="text-xl font-semibold text-primary">Data product mesh</h1>
        <p className="mt-3xs max-w-3xl text-sm text-secondary">
          Products linked by what they actually have in common — shared upstream sources,
          shared entity keys, shared certified KPIs, similar stated purpose, and the
          people who query both. Every line says why it is there; a line nobody can
          explain is not drawn.
        </p>
      </header>

      <nav aria-label="Mesh mode" className="mb-lg">
        <ul className="flex flex-wrap gap-2xs">
          {MODES.map((entry) => (
            <li key={entry.code}>
              <Link
                href={`/mesh/data?mode=${entry.code}`}
                aria-current={mode === entry.code ? 'true' : undefined}
                title={entry.hint}
                className="demo-question-chip"
              >
                {entry.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {mode === 'domain' ? (
        <nav aria-label="Domain" className="mb-lg">
          <ul className="flex flex-wrap gap-2xs">
            {domains.map((code) => (
              <li key={code}>
                <Link
                  href={`/mesh/data?mode=domain&domain=${code}`}
                  aria-current={domain === code ? 'true' : undefined}
                  className="demo-question-chip"
                >
                  {code.replace(/_/g, ' ')}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}

      {mode === 'source' ? (
        <SourceAnchored
          sources={sourcesResult.ok ? sourcesResult.data.sources : []}
          selected={source}
          blast={blastResult && blastResult.ok ? blastResult.data : null}
        />
      ) : (
        <>
          <MeshDiagram
            nodes={graph.nodes}
            edges={graph.edges}
            title="Data product mesh"
            layout={graph.layout.svg as unknown as SvgLayout}
          />
          <section className="mt-xl">
            <h2 className="refusal-subhead">Every edge, as a table</h2>
            <p className="mt-2xs mb-md text-sm text-secondary">
              The same data the diagram is drawn from, ranked the same way.
            </p>
            <MeshTable
              rows={graph.table}
              hrefBase="/data-products"
              caption="Data product mesh edges"
            />
          </section>
        </>
      )}

      <p className="mt-xl text-2xs text-muted">
        Computed under rubric version{' '}
        <span className="font-mono">{graph.rubric_version_id}</span>.
      </p>
    </div>
  );
}

function SourceAnchored({
  sources,
  selected,
  blast,
}: {
  sources: SourceList['sources'];
  selected: string | undefined;
  blast: BlastRadius | null;
}) {
  return (
    <div>
      <nav aria-label="Source systems" className="mb-lg">
        <ul className="flex flex-wrap gap-2xs">
          {sources.map((entry) => (
            <li key={entry.source_id}>
              <Link
                href={`/mesh/data?mode=source&source=${entry.source_id}`}
                aria-current={selected === entry.source_id ? 'true' : undefined}
                className="demo-question-chip"
              >
                {entry.source_id}
                <span className="ms-3xs text-muted">({entry.downstream_products})</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {blast === null ? (
        <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
          Pick a source system. The blast radius answers the question you actually have
          before a schema change or an outage: who finds out the hard way?
        </p>
      ) : (
        <section>
          <h2 className="text-lg font-semibold text-primary">
            If {blast.source_id} changes
          </h2>
          <dl className="mt-md grid grid-cols-2 gap-md sm:grid-cols-4">
            <Figure label="Data products" value={String(blast.products.length)} />
            <Figure label="Agents" value={String(blast.agents.length)} />
            <Figure label="Live grants" value={String(blast.consumer_count)} />
            <Figure
              label="Highest sensitivity"
              value={
                blast.products
                  .map((product) => product.sensitivity_tier)
                  .sort()
                  .at(-1) ?? '—'
              }
            />
          </dl>

          <div className="answer-table-wrap mt-lg">
            <table className="answer-table">
              <caption className="sr-only">
                Data products downstream of {blast.source_id}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Data product</th>
                  <th scope="col">Domain</th>
                  <th scope="col">Sensitivity</th>
                  <th scope="col">Tier</th>
                  <th scope="col">Agents bound</th>
                  <th scope="col">Live grants</th>
                </tr>
              </thead>
              <tbody>
                {blast.products.map((product) => (
                  <tr key={product.product_id}>
                    <td>
                      <Link
                        href={`/data-products/${product.product_id}`}
                        className="hover:underline"
                      >
                        {product.name}
                      </Link>
                    </td>
                    <td>{product.domain_code.replace(/_/g, ' ')}</td>
                    <td>{product.sensitivity_tier}</td>
                    <td>{product.tier}</td>
                    <td className="tabular-nums">
                      {blast.agents.filter((a) => a.product_id === product.product_id).length}
                    </td>
                    <td className="tabular-nums">
                      {blast.consumers.find((c) => c.asset_id === product.product_id)
                        ?.consumers ?? 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="refusal-subhead">{label}</dt>
      <dd className="mt-3xs text-lg font-medium text-primary">{value}</dd>
    </div>
  );
}
