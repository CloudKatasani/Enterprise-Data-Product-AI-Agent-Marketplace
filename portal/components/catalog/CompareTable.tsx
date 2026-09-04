import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import type { ProductCard } from '@/lib/types';

/**
 * Compare mode.
 *
 * The same facts as the card, transposed so a reader compares like with like
 * down a column instead of scanning across cards. Rows are fixed and in the
 * card's own order, so switching between grid and compare does not reorder the
 * information.
 */
const ROWS: { label: string; render: (product: ProductCard) => React.ReactNode }[] = [
  { label: 'Certification', render: (p) => <Badge tone="certification" code={p.certification}>{p.certification}</Badge> },
  { label: 'Quality', render: (p) => (p.quality.composite === null ? 'not yet scored' : `${Math.round(p.quality.composite)} · ${p.quality.band ?? ''}`) },
  { label: 'Sensitivity', render: (p) => <Badge tone="sensitivity" code={p.sensitivity}>{p.sensitivity}</Badge> },
  { label: 'Tier', render: (p) => p.tier },
  { label: 'Grain', render: (p) => p.grain },
  { label: 'Freshness', render: (p) => p.freshness.target ?? 'not declared' },
  { label: 'Owner', render: (p) => p.owner.name },
  { label: 'Consumers', render: (p) => `${p.adoption.active_consumers} across ${p.adoption.distinct_teams} teams` },
  { label: 'Certified KPIs', render: (p) => p.certified_kpis.join(', ') },
  { label: 'Attached agents', render: (p) => (p.attached_agents.length > 0 ? p.attached_agents.join(', ') : 'none') },
  { label: 'Endpoints', render: (p) => p.endpoints.join(', ') },
  { label: 'Access', render: (p) => (p.access.granted ? 'granted' : <Link className="text-accent hover:underline" href={p.access.request_access_url}>request</Link>) },
];

export function CompareTable({ products }: { products: ProductCard[] }) {
  if (products.length === 0) {
    return (
      <p className="rounded-lg border border-subtle bg-sunken p-lg text-sm text-secondary">
        Select products from the grid to compare them side by side.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <caption className="sr-only">Selected data products compared attribute by attribute</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 bg-page px-sm py-xs text-left text-2xs uppercase tracking-wide text-muted">
              Attribute
            </th>
            {products.map((product) => (
              <th key={product.product_id} scope="col" className="px-sm py-xs text-left align-bottom">
                <Link href={`/data-products/${product.product_id}`} className="text-sm font-semibold text-primary hover:underline">
                  {product.name}
                </Link>
                <p className="text-2xs font-normal text-muted">{product.product_id}</p>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.label} className="border-t border-subtle">
              <th scope="row" className="sticky left-0 bg-page px-sm py-xs text-left text-xs font-medium text-secondary">
                {row.label}
              </th>
              {products.map((product) => (
                <td key={product.product_id} className="px-sm py-xs align-top text-secondary">
                  {row.render(product)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
