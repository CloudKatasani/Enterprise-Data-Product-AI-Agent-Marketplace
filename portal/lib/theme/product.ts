import 'server-only';

/**
 * Theme configuration.
 *
 * The product name is deliberately unset in source (I13). It is resolved here,
 * once, from the environment, and every surface renders the resolved token.
 * A missing value is a boot failure, not a fallback: the deployment is
 * misconfigured and rendering an unnamed marketplace would hide that.
 */
export interface ThemeConfig {
  readonly productName: string;
  readonly tenantId: string;
}

class ThemeConfigurationError extends Error {}

let cached: ThemeConfig | null = null;

export function getThemeConfig(): ThemeConfig {
  if (cached !== null) {
    return cached;
  }

  const productName = process.env.PRODUCT_NAME?.trim();
  const tenantId = process.env.TENANT_ID?.trim();

  const missing: string[] = [];
  if (!productName) missing.push('PRODUCT_NAME');
  if (!tenantId) missing.push('TENANT_ID');
  if (missing.length > 0) {
    throw new ThemeConfigurationError(
      `missing required environment variables: ${missing.join(', ')} (copy .env.example to .env)`,
    );
  }

  cached = { productName: productName as string, tenantId: tenantId as string };
  return cached;
}
