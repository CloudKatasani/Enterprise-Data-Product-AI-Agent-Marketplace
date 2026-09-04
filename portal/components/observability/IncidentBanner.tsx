import Link from 'next/link';

import type { Banner } from '@/lib/types';

/**
 * The banner an open incident puts on a listing (M10.2, M10.3).
 *
 * It appears because an incident is open and it clears when the incident
 * resolves. There is no owner control that hides it — the API has no such
 * parameter and this component has no such prop. An owner can add context, and
 * the context is shown here alongside the fact, never in place of it.
 *
 * Upstream trust propagates: an agent whose data product is late carries the
 * product's banner, because a consumer reading the agent page is relying on
 * that product whether or not they know its name.
 */
export function IncidentBanner({
  banners,
  on,
}: {
  banners: Banner[];
  on: string;
}) {
  if (banners.length === 0) return null;

  return (
    <div role="status" className="incident-stack">
      {banners.map((banner) => {
        const upstream = banner.origin_id !== on;
        return (
          <section
            key={banner.incident_id}
            className="incident-banner"
            data-severity={banner.severity}
          >
            <p className="incident-headline">
              <span className="incident-severity" data-severity={banner.severity}>
                {banner.severity}
              </span>{' '}
              {upstream ? (
                <>
                  Upstream:{' '}
                  <Link
                    href={`/data-products/${banner.origin_id}`}
                    className="underline"
                  >
                    {banner.origin_id}
                  </Link>{' '}
                  has an open {banner.signal.replace(/_/g, ' ')} incident.
                </>
              ) : (
                <>An open {banner.signal.replace(/_/g, ' ')} incident.</>
              )}
            </p>
            {banner.guarantee_breached ? (
              <p className="incident-detail">
                Breached guarantee — {banner.guarantee_breached}
              </p>
            ) : null}
            {banner.owner_context ? (
              <p className="incident-detail">
                <strong className="font-medium">From the owner:</strong>{' '}
                {banner.owner_context}
              </p>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
