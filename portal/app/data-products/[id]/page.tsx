import Link from 'next/link';
import { notFound } from 'next/navigation';

import { PRODUCT_TABS, renderTab } from '@/components/detail/ProductTabs';
import { TabBar } from '@/components/detail/Tabs';
import { Badge } from '@/components/ui/Badge';
import { QualityRing } from '@/components/ui/QualityRing';
import { ErrorState } from '@/components/ui/StateBoundary';
import { apiTry } from '@/lib/api';
import { NOT_FOUND } from '@/lib/http-status';
import type { ProductDetail } from '@/lib/types';

export const dynamic = 'force-dynamic';

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await apiTry<ProductDetail>(`/products/${id}`);
  return { title: result.ok ? result.data.card.name : id };
}

export default async function ProductDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const result = await apiTry<ProductDetail>(`/products/${id}`);

  if (!result.ok) {
    if (result.problem.status === NOT_FOUND) notFound();
    return (
      <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
        <ErrorState title="This product could not be loaded" detail={result.problem.detail} />
      </div>
    );
  }

  const detail = result.data;
  const card = detail.card;
  const requested = typeof query.tab === 'string' ? query.tab : 'overview';
  const active = PRODUCT_TABS.some((tab) => tab.code === requested) ? requested : 'overview';

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-2xl">
      <nav aria-label="Breadcrumb" className="mb-md text-xs text-muted">
        <Link href="/data-products" className="hover:text-primary">
          Data products
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="text-secondary">{card.product_id}</span>
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-lg border-b border-subtle pb-lg">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight text-primary">{card.name}</h1>
          <p className="mt-xs text-sm text-secondary">{card.purpose}</p>
          <div className="mt-sm flex flex-wrap gap-2xs">
            <Badge tone="certification" code={card.certification}>{card.certification}</Badge>
            <Badge tone="sensitivity" code={card.sensitivity}>{card.sensitivity}</Badge>
            <Badge>{card.tier}</Badge>
            <Badge>{card.industry.replace(/_/g, ' ')}</Badge>
            <Badge>{card.domain.replace(/_/g, ' ')}</Badge>
            <Badge>v{card.current_version}</Badge>
          </div>
          {card.incident ? (
            <p role="status" className="mt-sm rounded-md border border-strong bg-sunken px-md py-sm text-sm text-band-unfit">
              Open incident {card.incident.incident_id} ({card.incident.severity}) affects this
              product. Consumers of it have been notified.
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-lg">
          <div className="text-right">
            <p className="text-2xs uppercase tracking-wide text-muted">Owner</p>
            <p className="text-sm text-secondary">{card.owner.name}</p>
            <p className="mt-xs text-2xs uppercase tracking-wide text-muted">Consumers</p>
            <p className="text-sm text-secondary">
              {card.adoption.active_consumers} across {card.adoption.distinct_teams} teams
            </p>
          </div>
          <QualityRing composite={card.quality.composite} band={card.quality.band} />
          {card.access.granted ? (
            <span className="rounded-md border border-strong px-md py-sm text-sm text-status-ok">
              Access granted
            </span>
          ) : (
            <Link
              href={card.access.request_access_url}
              className="rounded-md bg-accent px-lg py-sm text-sm font-medium text-on-hero"
            >
              Request access
            </Link>
          )}
        </div>
      </header>

      <TabBar
        tabs={[...PRODUCT_TABS]}
        states={detail.tabs as unknown as Record<string, { state: never }>}
        active={active}
        basePath={`/data-products/${card.product_id}`}
      />

      <section className="pt-lg" aria-label={active.replace(/_/g, ' ')}>
        {renderTab(active, detail)}
      </section>
    </div>
  );
}
