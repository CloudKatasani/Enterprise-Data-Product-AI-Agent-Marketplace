import Link from 'next/link';

import { PolicyPreview } from '@/components/workflow/PolicyPreview';
import { PageMessage } from '@/components/ui/PageMessage';
import { apiPost, apiTry } from '@/lib/api';
import type { PolicyEvaluation, ProductCard } from '@/lib/types';

export const dynamic = 'force-dynamic';

const PURPOSES = [
  'analytics',
  'operational_planning',
  'regulatory_reporting',
  'risk_management',
  'customer_service',
  'retention_campaign',
  'fraud_investigation',
  'clinical_quality',
  'product_development',
  'model_training',
] as const;

/**
 * The access request form (section 14.1).
 *
 * Everything is in the URL — asset, purpose — so the evaluation runs on the
 * server and the consumer sees the real outcome before submitting. Changing the
 * purpose changes the preview, which is the single most useful thing this form
 * does: it teaches people what the estate's policy actually is, by showing them
 * the consequence of each choice as they make it.
 */
export default async function NewAccessRequestPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const asset = typeof params.asset === 'string' ? params.asset : '';
  const surface = typeof params.surface === 'string' ? params.surface : 'data_product';
  const purpose = typeof params.purpose === 'string' ? params.purpose : 'analytics';
  const assetType = surface === 'agent' ? 'agent' : 'data_product';

  if (!asset) {
    return (
      <PageMessage title="Request access">
        Pick an asset first. Every{' '}
        <Link href="/data-products" className="text-accent hover:underline">
          data product
        </Link>{' '}
        and{' '}
        <Link href="/agents" className="text-accent hover:underline">
          agent
        </Link>{' '}
        page has a request button that brings you here with the asset filled in.
      </PageMessage>
    );
  }

  const [product, evaluation] = await Promise.all([
    assetType === 'data_product'
      ? apiTry<{ card: ProductCard }>(`/products/${asset}`)
      : Promise.resolve(null),
    apiPost<PolicyEvaluation>('/requests/access/evaluate', {
      asset_type: assetType,
      asset_id: asset,
      purpose_code: purpose,
    }),
  ]);

  const name =
    product && product.ok ? product.data.card.name : asset;

  return (
    <div className="mx-auto max-w-screen-md px-lg py-xl">
      <p className="text-2xs uppercase tracking-wide text-muted">
        <Link href="/requests" className="hover:underline">
          Requests
        </Link>{' '}
        / new access request
      </p>
      <h1 className="mt-2xs text-xl font-semibold text-primary">Access to {name}</h1>
      <p className="mt-2xs text-sm text-secondary">
        Choose the purpose you need it for. The panel below is what will happen when you
        submit — not an estimate of it.
      </p>

      <fieldset className="mt-lg">
        <legend className="refusal-subhead">Purpose</legend>
        <ul className="mt-2xs flex flex-wrap gap-2xs">
          {PURPOSES.map((code) => (
            <li key={code}>
              <Link
                href={`/requests/new/access?asset=${asset}&surface=${surface}&purpose=${code}`}
                aria-current={code === purpose ? 'true' : undefined}
                className="demo-question-chip"
              >
                {code.replace(/_/g, ' ')}
              </Link>
            </li>
          ))}
        </ul>
      </fieldset>

      <div className="mt-lg">
        {evaluation.ok ? (
          <PolicyPreview evaluation={evaluation.data} />
        ) : (
          <PageMessage title="This asset could not be evaluated">
            {evaluation.problem.detail}
          </PageMessage>
        )}
      </div>
    </div>
  );
}
