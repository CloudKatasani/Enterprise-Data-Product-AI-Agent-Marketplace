import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import { QualityRing } from '@/components/ui/QualityRing';
import { StateBoundary } from '@/components/ui/StateBoundary';
import type {
  ConsumptionData,
  ContractData,
  EndpointRow,
  LineageEdgeRow,
  LineageMeshData,
  OverviewData,
  ProductDetail,
  QualityData,
  SchemaColumn,
  Tab,
  ValueData,
} from '@/lib/types';

/**
 * The eight product detail tabs, each rendering the payload the API assembled.
 *
 * No tab invents a value. Where the API returned `empty`, the boundary renders
 * what would produce the content; where it returned `partial_permission`, the
 * boundary renders the missing scope and the request link. That is why these
 * components hold no fallbacks of their own.
 */

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3xs border-b border-subtle py-sm sm:grid-cols-[220px_1fr]">
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="text-sm text-secondary">{children}</dd>
    </div>
  );
}

export function OverviewTab({ tab }: { tab: Tab<OverviewData> }) {
  const data = tab.data;
  return (
    <StateBoundary tab={tab} emptyTitle="No overview available">
      {data ? (
        <dl>
          <Row label="Purpose">{data.purpose}</Row>
          <Row label="Grain">{data.grain}</Row>
          <Row label="History">{data.history_months} months</Row>
          <Row label="Known limitations">
            <span className="whitespace-pre-line">{data.known_limitations}</span>
          </Row>
          <Row label="Owner">
            {data.owner.name} · {data.owner.team ?? 'no team recorded'}
          </Row>
          <Row label="Certified KPIs">
            <ul role="list" className="flex flex-wrap gap-2xs">
              {data.certified_kpis.map((kpi) => (
                <li key={kpi}>
                  <Link href={`/kpis/${kpi}`} className="text-accent hover:underline">
                    {kpi}
                  </Link>
                </li>
              ))}
            </ul>
          </Row>
          <Row label="Upstream sources">
            {data.upstream_sources.join(', ') || 'not yet harvested'}
          </Row>
          <Row label="Classification">
            <Badge tone="sensitivity" code={data.sensitivity}>
              {data.sensitivity}
            </Badge>
            <span className="ml-xs text-xs text-muted">
              derived from column classification, never written directly
            </span>
          </Row>
        </dl>
      ) : null}
    </StateBoundary>
  );
}

export function SchemaTab({
  tab,
}: {
  tab: Tab<{ columns: SchemaColumn[]; column_count: number }>;
}) {
  return (
    <StateBoundary tab={tab} emptyTitle="No columns declared or harvested yet">
      {tab.data ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-max border-collapse text-sm">
            <caption className="sr-only">
              {tab.data.column_count} columns with type, nullability and classification
            </caption>
            <thead>
              <tr className="border-b border-strong text-left text-2xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-sm py-xs">Column</th>
                <th scope="col" className="px-sm py-xs">Business name</th>
                <th scope="col" className="px-sm py-xs">Type</th>
                <th scope="col" className="px-sm py-xs">Null</th>
                <th scope="col" className="px-sm py-xs">Classification</th>
                <th scope="col" className="px-sm py-xs">Description</th>
              </tr>
            </thead>
            <tbody>
              {tab.data.columns.map((column) => (
                <tr key={column.name} className="border-b border-subtle align-top">
                  <td className="px-sm py-xs font-mono text-xs text-primary">{column.name}</td>
                  <td className="px-sm py-xs text-secondary">{column.business_name}</td>
                  <td className="px-sm py-xs text-secondary">{column.data_type}</td>
                  <td className="px-sm py-xs text-secondary">{column.nullable ? 'yes' : 'no'}</td>
                  <td className="px-sm py-xs">
                    <div className="flex flex-wrap gap-3xs">
                      {column.classification.length === 0 ? (
                        <span className="text-xs text-muted">—</span>
                      ) : (
                        column.classification.map((code) => (
                          <Badge key={code} tone="sensitivity" code={column.sensitivity}>
                            {code}
                          </Badge>
                        ))
                      )}
                      {column.masked_for_caller ? (
                        <span className="text-2xs text-band-watch">masked for you</span>
                      ) : null}
                    </div>
                  </td>
                  <td className="max-w-md px-sm py-xs text-secondary">{column.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </StateBoundary>
  );
}

export function QualityTab({ tab }: { tab: Tab<QualityData> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No quality snapshot computed yet">
      {tab.data ? (
        <div className="space-y-lg">
          {tab.data.current ? (
            <section className="flex flex-wrap items-center gap-lg rounded-lg border border-subtle bg-raised p-lg">
              <QualityRing
                composite={tab.data.current.composite}
                band={tab.data.current.band}
              />
              <div>
                <p className="text-md font-semibold text-primary">
                  {tab.data.current.band?.replace(/_/g, ' ')}
                </p>
                <p className="text-xs text-muted">
                  computed {tab.data.current.computed_at} under rubric{' '}
                  <code className="font-mono">{tab.data.current.rubric_version_id}</code>
                </p>
                {tab.data.current.blocker_applied ? (
                  <p className="mt-2xs text-xs text-band-unfit">
                    capped by hard blocker: {tab.data.current.blocker_applied}
                  </p>
                ) : null}
              </div>
              <dl className="ml-auto grid grid-cols-3 gap-x-lg gap-y-2xs text-xs">
                {Object.entries(tab.data.current.dimensions).map(
                  ([dimension, value]) => (
                    <div key={dimension}>
                      <dt className="text-muted">{dimension}</dt>
                      <dd className="tabular-nums text-secondary">
                        {value === null ? '—' : Math.round(value)}
                      </dd>
                    </div>
                  ),
                )}
              </dl>
            </section>
          ) : null}

          <section>
            <h3 className="text-sm font-semibold text-primary">Rules</h3>
            <ul role="list" className="mt-xs space-y-2xs text-sm">
              {tab.data.rules.map((rule) => (
                <li key={rule.rule_id} className="text-secondary">
                  <code className="font-mono text-xs text-primary">{rule.rule_id}</code>{' '}
                  {rule.dimension} · {rule.rule_type} ·{' '}
                  <span className="text-muted">severity {rule.severity}</span>
                </li>
              ))}
            </ul>
          </section>

          {tab.data.contributing_results.length > 0 ? (
            <section>
              <h3 className="text-sm font-semibold text-primary">Contributing results</h3>
              <div className="mt-xs overflow-x-auto">
                <table className="w-full min-w-max border-collapse text-sm">
                  <caption className="sr-only">
                    Rule results contributing to the current quality composite
                  </caption>
                  <thead>
                    <tr className="border-b border-strong text-left text-2xs uppercase tracking-wide text-muted">
                      <th scope="col" className="px-sm py-xs">Rule</th>
                      <th scope="col" className="px-sm py-xs">Dimension</th>
                      <th scope="col" className="px-sm py-xs">Threshold</th>
                      <th scope="col" className="px-sm py-xs">Observed</th>
                      <th scope="col" className="px-sm py-xs">Passed</th>
                      <th scope="col" className="px-sm py-xs">Evaluated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tab.data.contributing_results.map((result) => (
                      <tr key={result.result_id} className="border-b border-subtle">
                        <td className="px-sm py-xs font-mono text-xs">{result.rule_id}</td>
                        <td className="px-sm py-xs text-secondary">{result.dimension}</td>
                        <td className="px-sm py-xs tabular-nums text-secondary">
                          {result.threshold_pct ?? '—'}
                        </td>
                        <td className="px-sm py-xs tabular-nums text-secondary">
                          {result.observed_pct ?? '—'}
                        </td>
                        <td className="px-sm py-xs">
                          <span className={result.passed ? 'text-status-ok' : 'text-status-error'}>
                            {result.passed ? 'pass' : 'fail'}
                          </span>
                        </td>
                        <td className="px-sm py-xs text-muted">{result.evaluated_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </StateBoundary>
  );
}

export function ContractTab({ tab }: { tab: Tab<ContractData> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No data contract published">
      {tab.data ? (
        <div className="space-y-lg">
          <section>
            <h3 className="text-sm font-semibold text-primary">Guarantees</h3>
            <dl className="mt-xs">
              {tab.data.guarantees.map((guarantee) => (
                <Row key={guarantee.dimension} label={guarantee.dimension}>
                  {guarantee.target_text}
                  <span className="ml-xs text-xs text-muted">
                    measured {guarantee.measurement_window} at {guarantee.measured_at_grain}
                    {guarantee.reference_system ? ` against ${guarantee.reference_system}` : ''}
                  </span>
                </Row>
              ))}
            </dl>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-primary">Consumer obligations</h3>
            <ul role="list" className="mt-xs list-inside list-disc space-y-3xs text-sm text-secondary">
              {tab.data.active.consumer_obligations.map((obligation) => (
                <li key={obligation}>{obligation}</li>
              ))}
            </ul>
          </section>

          <dl>
            <Row label="Version">{tab.data.active.semver}</Row>
            <Row label="Schema stability">{tab.data.active.schema_stability}</Row>
            <Row label="Deprecation">
              {tab.data.active.deprecation.notice_days} days notice, minimum{' '}
              {tab.data.active.deprecation.minimum_parallel_run_days} days parallel run
            </Row>
            <Row label="Support">
              {tab.data.active.support.hours} · P1 within{' '}
              {tab.data.active.support.p1_response_minutes} minutes ·{' '}
              {tab.data.active.support.on_call}
            </Row>
            <Row label="Residency">{tab.data.active.classification.residency.join(', ')}</Row>
            <Row label="Breach process">{tab.data.active.breach_process}</Row>
          </dl>
        </div>
      ) : null}
    </StateBoundary>
  );
}

export function EndpointsTab({ tab }: { tab: Tab<{ endpoints: EndpointRow[] }> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No consumption endpoints published">
      {tab.data ? (
        <ul role="list" className="space-y-sm">
          {tab.data.endpoints.map((endpoint) => (
            <li
              key={endpoint.surface}
              className="rounded-lg border border-subtle bg-raised p-md"
            >
              <div className="flex flex-wrap items-center justify-between gap-sm">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-primary">
                  {endpoint.surface}
                </h3>
                <span
                  className={
                    endpoint.granted
                      ? 'text-2xs font-medium text-status-ok'
                      : 'text-2xs font-medium text-band-watch'
                  }
                >
                  {endpoint.granted ? 'available to you' : 'needs a grant'}
                </span>
              </div>
              <p className="mt-2xs break-all font-mono text-xs text-secondary">{endpoint.uri}</p>
              <p className="mt-2xs text-xs text-muted">
                {endpoint.auth_mode} · scope <code>{endpoint.required_scope}</code>
                {endpoint.row_limit ? ` · row limit ${endpoint.row_limit}` : ''}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </StateBoundary>
  );
}

export function LineageMeshTab({ tab }: { tab: Tab<LineageMeshData> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No lineage harvested and no mesh edge computed">
      {tab.data ? (
        <div className="space-y-lg">
          <section>
            <h3 className="text-sm font-semibold text-primary">Upstream</h3>
            <EdgeTable rows={tab.data.upstream} idKey="id" />
          </section>
          <section>
            <h3 className="text-sm font-semibold text-primary">Downstream</h3>
            <EdgeTable rows={tab.data.downstream} idKey="id" />
          </section>
          <section>
            <h3 className="text-sm font-semibold text-primary">Mesh neighbourhood</h3>
            <EdgeTable rows={tab.data.mesh} idKey="neighbour" />
            {tab.data.held_for_review > 0 ? (
              <p className="mt-xs text-xs text-muted">
                {tab.data.held_for_review} edge(s) are held below the confidence floor and
                are not rendered until a steward reviews them.
              </p>
            ) : null}
          </section>
        </div>
      ) : null}
    </StateBoundary>
  );
}

function EdgeTable({ rows, idKey }: { rows: LineageEdgeRow[]; idKey: 'id' | 'neighbour' }) {
  if (rows.length === 0) {
    return <p className="mt-xs text-sm text-muted">None recorded.</p>;
  }
  return (
    <div className="mt-xs overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <caption className="sr-only">
          Related assets with the relationship, the confidence and the reason for the edge
        </caption>
        <thead>
          <tr className="border-b border-strong text-left text-2xs uppercase tracking-wide text-muted">
            <th scope="col" className="px-sm py-xs">Asset</th>
            <th scope="col" className="px-sm py-xs">Relationship</th>
            <th scope="col" className="px-sm py-xs">Confidence</th>
            <th scope="col" className="px-sm py-xs">Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row[idKey] ?? index}`} className="border-b border-subtle align-top">
              <td className="px-sm py-xs font-mono text-xs text-primary">{row[idKey]}</td>
              <td className="px-sm py-xs text-secondary">{row.relationship ?? row.edge_type}</td>
              <td className="px-sm py-xs tabular-nums text-secondary">{row.confidence}</td>
              <td className="max-w-lg px-sm py-xs text-secondary">{row.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ConsumptionTab({ tab }: { tab: Tab<ConsumptionData> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No usage recorded yet">
      {tab.data ? (
        <div className="overflow-x-auto">
          <p className="mb-xs text-xs text-muted">
            Showing {tab.data.scope} consumption.
          </p>
          <table className="w-full min-w-max border-collapse text-sm">
            <caption className="sr-only">
              Daily consumption: active consumers, teams, queries and permission denials
            </caption>
            <thead>
              <tr className="border-b border-strong text-left text-2xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-sm py-xs">Date</th>
                <th scope="col" className="px-sm py-xs">Consumers</th>
                <th scope="col" className="px-sm py-xs">Teams</th>
                <th scope="col" className="px-sm py-xs">Queries</th>
                <th scope="col" className="px-sm py-xs">Denied</th>
              </tr>
            </thead>
            <tbody>
              {tab.data.daily.map((day) => (
                <tr key={day.activity_date} className="border-b border-subtle">
                  <td className="px-sm py-xs text-secondary">{day.activity_date}</td>
                  <td className="px-sm py-xs tabular-nums text-secondary">
                    {day.active_consumers}
                  </td>
                  <td className="px-sm py-xs tabular-nums text-secondary">{day.distinct_teams}</td>
                  <td className="px-sm py-xs tabular-nums text-secondary">{day.query_count}</td>
                  <td className="px-sm py-xs tabular-nums text-band-watch">{day.denied_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </StateBoundary>
  );
}

export function ValueTab({ tab }: { tab: Tab<ValueData> }) {
  return (
    <StateBoundary tab={tab} emptyTitle="No value case authored">
      {tab.data ? (
        <div className="space-y-lg">
          <dl>
            <Row label="Business outcome">{tab.data.case.business_outcome}</Row>
            <Row label="Baseline">
              {tab.data.case.baseline_method} · captured {tab.data.case.baseline_captured}
            </Row>
            <Row label="Benefit model">
              <code className="font-mono text-xs">{tab.data.case.benefit_model}</code>
            </Row>
            <Row label="Attribution confidence">{tab.data.case.attribution_confidence}</Row>
            <Row label="Review">
              last reviewed {tab.data.case.last_reviewed}, due {tab.data.case.review_due}
            </Row>
          </dl>

          <section>
            <h3 className="text-sm font-semibold text-primary">Assumptions</h3>
            <p className="mt-3xs text-xs text-muted">
              Every figure derived from these carries the sample size and date beside it.
            </p>
            <ul role="list" className="mt-xs space-y-xs">
              {tab.data.assumptions.map((assumption) => (
                <li
                  key={assumption.text}
                  className="rounded-md border border-subtle bg-raised px-md py-sm text-sm"
                >
                  <p className="text-primary">
                    {assumption.text}:{' '}
                    <span className="tabular-nums">{assumption.value}</span> {assumption.unit}
                  </p>
                  <p className="mt-3xs text-xs text-muted">
                    {assumption.sample_size
                      ? `sample size ${assumption.sample_size} · `
                      : 'no sample size recorded · '}
                    {assumption.source} · {assumption.dated}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}
    </StateBoundary>
  );
}

export const PRODUCT_TABS = [
  { code: 'overview', label: 'Overview' },
  { code: 'schema', label: 'Schema' },
  { code: 'quality', label: 'Quality' },
  { code: 'contract', label: 'Contract' },
  { code: 'endpoints', label: 'Endpoints' },
  { code: 'lineage_mesh', label: 'Lineage & Mesh' },
  { code: 'consumption', label: 'Consumption' },
  { code: 'value', label: 'Value' },
] as const;

export type ProductTabCode = (typeof PRODUCT_TABS)[number]['code'];

export function renderTab(code: string, detail: ProductDetail) {
  switch (code) {
    case 'schema':
      return <SchemaTab tab={detail.tabs.schema} />;
    case 'quality':
      return <QualityTab tab={detail.tabs.quality} />;
    case 'contract':
      return <ContractTab tab={detail.tabs.contract} />;
    case 'endpoints':
      return <EndpointsTab tab={detail.tabs.endpoints} />;
    case 'lineage_mesh':
      return <LineageMeshTab tab={detail.tabs.lineage_mesh} />;
    case 'consumption':
      return <ConsumptionTab tab={detail.tabs.consumption} />;
    case 'value':
      return <ValueTab tab={detail.tabs.value} />;
    default:
      return <OverviewTab tab={detail.tabs.overview} />;
  }
}
