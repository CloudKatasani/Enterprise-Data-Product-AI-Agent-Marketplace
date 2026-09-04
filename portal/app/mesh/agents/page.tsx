import Link from 'next/link';

import { MeshDiagram, type SvgLayout } from '@/components/mesh/MeshDiagram';
import { MeshTable } from '@/components/mesh/MeshTable';
import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { MeshGraph } from '@/lib/types';

export const dynamic = 'force-dynamic';

const MODES = [
  { code: 'force', label: 'All relationships' },
  { code: 'domain', label: 'By domain' },
  { code: 'duplication', label: 'Consolidation candidates' },
] as const;

interface Divergence {
  shared_coverage: { kpi_id: string; kpi_name: string; unit: string; agents: string[] }[];
  cross_product: { kpi_id: string; kpi_name: string; source_of_record: string;
                   claimed_by: string[] }[];
}

export default async function AgentMeshPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const mode = typeof params.mode === 'string' ? params.mode : 'force';
  const domain = typeof params.domain === 'string' ? params.domain : undefined;

  const [graphResult, divergenceResult] = await Promise.all([
    apiTry<MeshGraph>('/mesh/agents', { mode, domain }),
    apiTry<Divergence>('/mesh/divergence'),
  ]);

  if (!graphResult.ok) {
    return <PageMessage title="The mesh is unavailable">{graphResult.problem.detail}</PageMessage>;
  }

  const graph = graphResult.data;
  const domains = [...new Set(graph.nodes.map((node) => node.domain))].sort();
  const shared = divergenceResult.ok ? divergenceResult.data.shared_coverage : [];

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <header className="mb-lg">
        <h1 className="text-xl font-semibold text-primary">Agent mesh</h1>
        <p className="mt-3xs max-w-3xl text-sm text-secondary">
          Agents linked by shared data products, overlapping KPI coverage, similar stated
          capability, domain and co-usage. Two agents covering the same KPI over the same
          product are a divergence risk before they are a duplication one — they will be
          asked the same question and can answer it differently.
        </p>
      </header>

      <nav aria-label="Mesh mode" className="mb-lg">
        <ul className="flex flex-wrap gap-2xs">
          {MODES.map((entry) => (
            <li key={entry.code}>
              <Link
                href={`/mesh/agents?mode=${entry.code}`}
                aria-current={mode === entry.code ? 'true' : undefined}
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
                  href={`/mesh/agents?mode=domain&domain=${code}`}
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

      <MeshDiagram
        nodes={graph.nodes}
        edges={graph.edges}
        title="Agent mesh"
        layout={graph.layout.svg as unknown as SvgLayout}
      />

      <section className="mt-xl">
        <h2 className="refusal-subhead">Every edge, as a table</h2>
        <p className="mt-2xs mb-md text-sm text-secondary">
          The same data the diagram is drawn from, ranked the same way.
        </p>
        <MeshTable rows={graph.table} hrefBase="/agents" caption="Agent mesh edges" />
      </section>

      <section className="mt-xl">
        <h2 className="refusal-subhead">Shared KPI coverage</h2>
        {shared.length === 0 ? (
          <p className="mt-2xs rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
            No certified KPI is answered by more than one agent, so there is nothing here
            that two agents could disagree about. That is worth being able to state.
          </p>
        ) : (
          <div className="answer-table-wrap mt-2xs">
            <table className="answer-table">
              <caption className="sr-only">
                KPIs covered by more than one agent
              </caption>
              <thead>
                <tr>
                  <th scope="col">KPI</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Answered by</th>
                </tr>
              </thead>
              <tbody>
                {shared.map((row) => (
                  <tr key={row.kpi_id}>
                    <td>
                      <span className="font-mono text-2xs text-muted">{row.kpi_id}</span>
                      <br />
                      {row.kpi_name}
                    </td>
                    <td>{row.unit}</td>
                    <td>
                      {row.agents.map((agent) => (
                        <Link
                          key={agent}
                          href={`/agents/${agent}`}
                          className="mr-2xs hover:underline"
                        >
                          {agent}
                        </Link>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="mt-xl text-2xs text-muted">
        Computed under rubric version{' '}
        <span className="font-mono">{graph.rubric_version_id}</span>.
      </p>
    </div>
  );
}
