import { cn } from '@/lib/cn';

/**
 * The vocabulary badges. Colour is resolved from the *code* — a certification,
 * a band, a sensitivity tier — never from a number, so the same encoding is
 * used on the card, the detail page and the mesh (13.3).
 */

const BAND_CLASS: Record<string, string> = {
  exemplary: 'text-band-exemplary border-band-exemplary',
  healthy: 'text-band-healthy border-band-healthy',
  watch: 'text-band-watch border-band-watch',
  at_risk: 'text-band-at-risk border-band-at-risk',
  unfit: 'text-band-unfit border-band-unfit',
};

const CERTIFICATION_CLASS: Record<string, string> = {
  certified: 'text-band-exemplary border-band-exemplary',
  published: 'text-accent border-accent',
  beta: 'text-band-watch border-band-watch',
  deprecated: 'text-muted border-strong',
};

const SENSITIVITY_CLASS: Record<string, string> = {
  public: 'text-secondary border-strong',
  internal: 'text-band-healthy border-band-healthy',
  confidential: 'text-band-watch border-band-watch',
  restricted: 'text-band-unfit border-band-unfit',
};

export function Badge({
  children,
  tone = 'neutral',
  code,
  title,
}: {
  children: React.ReactNode;
  tone?: 'neutral' | 'band' | 'certification' | 'sensitivity';
  code?: string;
  title?: string;
}) {
  const palette =
    tone === 'band'
      ? BAND_CLASS
      : tone === 'certification'
        ? CERTIFICATION_CLASS
        : tone === 'sensitivity'
          ? SENSITIVITY_CLASS
          : {};
  const resolved = (code && palette[code]) || 'text-secondary border-strong';

  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center rounded-pill border px-xs py-3xs text-2xs font-medium uppercase tracking-wide',
        resolved,
      )}
    >
      {children}
    </span>
  );
}
