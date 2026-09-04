import 'server-only';

/**
 * Locale and writing direction (M12.4).
 *
 * The portal ships one language. What it must not do is *assume* one: a layout
 * that only works left-to-right, or only at English string lengths, is a layout
 * that has to be rebuilt rather than translated, and the rebuild is where the
 * budget goes.
 *
 * So two things are true of every surface here.
 *
 * **Direction is a property of the document**, set once on `<html>` from the
 * configured locale, and every style is written in logical properties —
 * `margin-inline-start`, `text-align: start`, `border-inline-start` — so
 * mirroring is a `dir` attribute rather than a stylesheet. CI asserts no
 * physical direction property survives in the portal.
 *
 * **Layouts hold at 35% expansion.** German and Finnish run roughly a third
 * longer than English, and a design that fits its own copy exactly is a design
 * that breaks on the first translation. The a11y suite renders the top surfaces
 * with expanded strings and checks nothing overflows its reserved box.
 */

/** Locales whose script runs right to left. */
const RTL_LANGUAGES = new Set(['ar', 'he', 'fa', 'ur', 'yi', 'dv', 'ps', 'ckb']);

export const DEFAULT_LOCALE = 'en';

export interface LocaleConfig {
  locale: string;
  language: string;
  direction: 'ltr' | 'rtl';
}

export function getLocale(): LocaleConfig {
  const locale = (process.env.PORTAL_LOCALE || DEFAULT_LOCALE).trim() || DEFAULT_LOCALE;
  const language = locale.split('-')[0]?.toLowerCase() ?? DEFAULT_LOCALE;
  return {
    locale,
    language,
    direction: RTL_LANGUAGES.has(language) ? 'rtl' : 'ltr',
  };
}
