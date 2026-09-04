import type { Config } from 'tailwindcss';

/**
 * Tailwind is wired straight onto the CSS custom properties in styles/tokens/.
 * No colour, radius or spacing value is written here as a literal: the token
 * file is the single source and the lint rule keeps it that way (I13).
 */
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'var(--surface-page)',
        raised: 'var(--surface-raised)',
        sunken: 'var(--surface-sunken)',
        inverse: 'var(--surface-inverse)',
        hero: 'var(--surface-hero)',
        subtle: 'var(--border-subtle)',
        strong: 'var(--border-strong)',
        primary: 'var(--text-primary)',
        secondary: 'var(--text-secondary)',
        muted: 'var(--text-muted)',
        'on-hero': 'var(--text-on-hero)',
        accent: 'var(--colour-accent-500)',
        'accent-strong': 'var(--colour-accent-600)',
        'band-exemplary': 'var(--colour-band-exemplary)',
        'band-healthy': 'var(--colour-band-healthy)',
        'band-watch': 'var(--colour-band-watch)',
        'band-at-risk': 'var(--colour-band-at-risk)',
        'band-unfit': 'var(--colour-band-unfit)',
        'status-ok': 'var(--colour-status-ok)',
        'status-warn': 'var(--colour-status-warn)',
        'status-error': 'var(--colour-status-error)',
        'status-info': 'var(--colour-status-info)',
      },
      borderColor: {
        DEFAULT: 'var(--border-subtle)',
      },
      spacing: {
        '3xs': 'var(--space-3xs)',
        '2xs': 'var(--space-2xs)',
        xs: 'var(--space-xs)',
        sm: 'var(--space-sm)',
        md: 'var(--space-md)',
        lg: 'var(--space-lg)',
        xl: 'var(--space-xl)',
        '2xl': 'var(--space-2xl)',
        '3xl': 'var(--space-3xl)',
        '4xl': 'var(--space-4xl)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        pill: 'var(--radius-pill)',
      },
      fontSize: {
        '2xs': 'var(--text-2xs)',
        xs: 'var(--text-xs)',
        sm: 'var(--text-sm)',
        base: 'var(--text-base)',
        md: 'var(--text-md)',
        lg: 'var(--text-lg)',
        xl: 'var(--text-xl)',
        '2xl': 'var(--text-2xl)',
        '3xl': 'var(--text-3xl)',
        '4xl': 'var(--text-4xl)',
      },
      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },
      boxShadow: {
        raised: 'var(--elevation-raised)',
        overlay: 'var(--elevation-overlay)',
      },
      transitionTimingFunction: {
        standard: 'var(--ease-standard)',
        entrance: 'var(--ease-entrance)',
        exit: 'var(--ease-exit)',
      },
      transitionDuration: {
        micro: 'var(--duration-micro)',
        base: 'var(--duration-base)',
        slow: 'var(--duration-slow)',
      },
    },
  },
  plugins: [],
};

export default config;
