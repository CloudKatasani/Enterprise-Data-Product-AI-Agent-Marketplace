/**
 * Rendering a measured number in the unit the server says it is in.
 *
 * The API states a finding's unit alongside its number because the unit
 * belongs to the signal, not to the page: a reader shown "0.0666" and "79" in
 * one column has been told the arithmetic and not the meaning. Nothing here
 * rescales anything — `Intl.NumberFormat` takes a fraction and renders a
 * percentage itself, so the portal never carries a conversion factor that
 * could drift from the server's.
 */

export const UNIT_MINUTES = 'minutes';
export const UNIT_FRACTION = 'fraction';
export const UNIT_POINTS = 'points';
export const UNIT_COUNT = 'count';
export const UNIT_MULTIPLE = 'multiple';

const percent = new Intl.NumberFormat(undefined, {
  style: 'percent',
  maximumFractionDigits: 1,
});

const decimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

/** A measured value, in words, in its own unit. */
export function inUnit(value: number, unit: string): string {
  switch (unit) {
    case UNIT_FRACTION:
      return percent.format(value);
    case UNIT_MINUTES:
      return `${decimal.format(value)} min`;
    case UNIT_POINTS:
      return `${decimal.format(value)} pts`;
    case UNIT_MULTIPLE:
      return `${decimal.format(value)}×`;
    case UNIT_COUNT:
    default:
      return decimal.format(value);
  }
}

/**
 * A count with its noun, agreeing in number.
 *
 * "1 products" is the kind of thing a reader notices and a writer never does.
 * English pluralisation is irregular enough that a rule would be wrong more
 * often than it is right, so the caller states both forms.
 */
export function count(value: number, singular: string, plural: string): string {
  return `${value.toLocaleString()} ${value === 1 ? singular : plural}`;
}
