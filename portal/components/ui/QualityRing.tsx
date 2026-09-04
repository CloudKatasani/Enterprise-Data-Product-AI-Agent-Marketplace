import { cn } from '@/lib/cn';

/**
 * The quality composite as a ring.
 *
 * The sweep is driven by a CSS custom property carrying the score, so the
 * geometry lives in CSS and the component carries no number of its own. The
 * ring animates once on first viewport entry (13.2) and is static otherwise;
 * the animation is defined in the stylesheet and animates only `transform`.
 */
export function QualityRing({
  composite,
  band,
  size = 'md',
}: {
  composite: number | null;
  band: string | null;
  size?: 'sm' | 'md';
}) {
  if (composite === null) {
    return (
      <span
        className="quality-ring quality-ring--unscored"
        data-size={size}
        role="img"
        aria-label="Not yet scored"
        title="No quality snapshot has been computed for this product yet"
      >
        <span className="quality-ring__value">—</span>
      </span>
    );
  }

  const rounded = Math.round(composite);
  return (
    <span
      className={cn('quality-ring')}
      data-size={size}
      data-band={band ?? 'unscored'}
      style={{ ['--quality-value' as string]: String(rounded) }}
      role="img"
      aria-label={`Quality composite ${rounded} out of 100, band ${band ?? 'unscored'}`}
    >
      <span className="quality-ring__value">{rounded}</span>
    </span>
  );
}
