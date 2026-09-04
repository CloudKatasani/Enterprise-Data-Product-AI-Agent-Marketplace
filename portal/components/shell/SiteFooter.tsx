import Link from 'next/link';

const FOOTER_LINKS = [
  { href: '/academy', label: 'Academy' },
  { href: '/console/owner', label: 'Owner console' },
  { href: '/console/steward', label: 'Steward console' },
  { href: '/admin', label: 'Administration' },
] as const;

export function SiteFooter({ productName }: { productName: string }) {
  return (
    <footer className="mt-4xl border-t border-subtle bg-raised">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-md px-lg py-lg">
        <p className="text-xs text-muted">
          {productName} — governed data products and AI agents.
        </p>
        <nav aria-label="Secondary">
          <ul className="flex flex-wrap gap-md">
            {FOOTER_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="text-xs text-secondary hover:text-primary">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
