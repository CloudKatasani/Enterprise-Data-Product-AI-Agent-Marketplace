import Link from 'next/link';

const PRIMARY_NAV = [
  { href: '/discover', label: 'Discover' },
  { href: '/data-products', label: 'Data products' },
  { href: '/agents', label: 'Agents' },
  { href: '/mesh/data', label: 'Mesh' },
  { href: '/demand', label: 'Demand' },
  { href: '/observability', label: 'Observability' },
  { href: '/academy', label: 'Academy' },
] as const;

export function SiteHeader({ productName }: { productName: string }) {
  return (
    <header className="border-b border-subtle bg-raised">
      <div className="mx-auto flex max-w-screen-2xl items-center gap-lg px-lg py-sm">
        <Link href="/" className="text-md font-semibold tracking-tight text-primary">
          {productName}
        </Link>
        <nav aria-label="Primary" className="flex-1">
          <ul className="flex flex-wrap items-center gap-md">
            {PRIMARY_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="text-sm text-secondary transition-colors duration-micro ease-standard hover:text-primary"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <Link
          href="/requests"
          className="rounded-md border border-strong px-md py-2xs text-sm text-primary"
        >
          My requests
        </Link>
      </div>
    </header>
  );
}
