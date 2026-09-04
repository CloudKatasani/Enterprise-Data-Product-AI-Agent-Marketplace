import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { NextConfig } from 'next';

/**
 * The repository keeps one .env at its root (BUILD.md section 5), while Next
 * looks for one beside the app. Load the root file here, without overriding a
 * variable that the process already carries, so `cp .env.example .env` is the
 * only setup step a developer performs.
 */
function loadRootEnv(): void {
  try {
    const raw = readFileSync(resolve(process.cwd(), '..', '.env'), 'utf8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (trimmed === '' || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
      const separator = trimmed.indexOf('=');
      const key = trimmed.slice(0, separator).trim();
      const value = trimmed.slice(separator + 1).trim();
      if (process.env[key] === undefined) {
        process.env[key] = value;
      }
    }
  } catch {
    // No root .env: the process environment is expected to carry the variables
    // (this is how CI and container deployments run).
  }
}

loadRootEnv();

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    optimizePackageImports: ['lucide-react', 'recharts'],
  },
  eslint: {
    dirs: ['app', 'components', 'lib'],
  },
};

export default config;
