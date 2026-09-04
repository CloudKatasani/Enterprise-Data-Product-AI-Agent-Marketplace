import 'server-only';

/**
 * Portal environment validation. Mirrors services/common/config.py: the app
 * refuses to render with a missing variable rather than degrading to a
 * permissive default (BUILD.md rule 7).
 */
const REQUIRED = ['PRODUCT_NAME', 'TENANT_ID', 'API_BASE_URL', 'OIDC_ISSUER'] as const;

export function assertPortalEnvironment(): void {
  const missing = REQUIRED.filter((name) => {
    const value = process.env[name];
    return value === undefined || value.trim() === '';
  });
  if (missing.length > 0) {
    throw new Error(
      `portal cannot boot; missing environment variables: ${missing.join(', ')}`,
    );
  }
}

export function apiBaseUrl(): string {
  const value = process.env.API_BASE_URL;
  if (value === undefined || value.trim() === '') {
    throw new Error('API_BASE_URL is not set');
  }
  return value.replace(/\/+$/, '');
}
