import Link from 'next/link';

import { Badge } from '@/components/ui/Badge';
import { QualityRing } from '@/components/ui/QualityRing';
import type { ProductCard as ProductCardData } from '@/lib/types';
import { count } from '@/lib/units';

/**
 * The product card: twelve elements in fixed positions (BUILD.md section 12).
 *
 *   1 name            2 certification ring   3 quality composite
 *   4 sensitivity     5 industry / domain    6 purpose
 *   7 freshness       8 owner                9 adoption
 *  10 attached agents 11 certified KPIs     12 access state
 *
 * There is no per-card variation. Consistency is what makes the grid scannable,
 * and it is what lets the landing ribbon reuse this exact component at 88%.
 */
export function ProductCard({ product }: { product: ProductCardData }) {
  const href = `/data-products/${product.product_id}`;

  return (
    <li className="product-card">
      <div className="flex items-start justify-between gap-sm">
        <div className="min-w-0">
          <h3 className="truncate text-md font-semibold text-primary">
            <Link href={href} className="hover:underline">
              {product.name}
            </Link>
          </h3>
          <p className="mt-3xs text-2xs uppercase tracking-wide text-muted">
            {product.industry.replace(/_/g, ' ')} · {product.domain.replace(/_/g, ' ')}
          </p>
        </div>
        <QualityRing composite={product.quality.composite} band={product.quality.band} />
      </div>

      <div className="flex flex-wrap gap-2xs">
        <Badge tone="certification" code={product.certification}>
          {product.certification}
        </Badge>
        <Badge tone="sensitivity" code={product.sensitivity} title="Derived from column classification">
          {product.sensitivity}
        </Badge>
        {product.quality.band ? (
          <Badge tone="band" code={product.quality.band}>
            {product.quality.band.replace(/_/g, ' ')}
          </Badge>
        ) : (
          <Badge>unscored</Badge>
        )}
        {product.incident ? (
          <Badge tone="band" code="at_risk" title={`Open incident ${product.incident.incident_id}`}>
            incident {product.incident.severity}
          </Badge>
        ) : null}
      </div>

      <p className="line-clamp-3 text-sm text-secondary">{product.purpose}</p>

      <dl className="grid grid-cols-2 gap-x-sm gap-y-2xs text-xs">
        <div>
          <dt className="text-muted">Freshness</dt>
          <dd className="text-secondary">{product.freshness.target ?? 'not declared'}</dd>
        </div>
        <div>
          <dt className="text-muted">Owner</dt>
          <dd className="truncate text-secondary">{product.owner.name}</dd>
        </div>
        <div>
          <dt className="text-muted">Consumers</dt>
          <dd className="text-secondary">
            {product.adoption.active_consumers} across{' '}
            {count(product.adoption.distinct_teams, 'team', 'teams')}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Agents</dt>
          <dd className="text-secondary">
            {product.attached_agents.length > 0
              ? product.attached_agents.join(', ')
              : 'none attached'}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-muted">Certified KPIs</dt>
          <dd className="truncate text-secondary">{product.certified_kpis.join(', ')}</dd>
        </div>
      </dl>

      <div className="flex items-center justify-between gap-sm border-t border-subtle pt-sm">
        <span className="text-2xs text-muted">{product.endpoints.join(' · ')}</span>
        {product.access.granted ? (
          <span className="text-2xs font-medium text-status-ok">Access granted</span>
        ) : (
          <Link
            href={product.access.request_access_url}
            className="text-2xs font-medium text-accent hover:underline"
          >
            Request access
          </Link>
        )}
      </div>
    </li>
  );
}
