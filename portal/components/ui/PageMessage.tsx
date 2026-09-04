/**
 * A whole page that has one thing to say.
 *
 * Used where a surface cannot render its normal content — nothing to show, a
 * dependency unreachable — and the honest response is a sentence rather than an
 * empty frame. It owns the page's single `h1`, so a route that falls back to it
 * still has exactly one.
 */
export function PageMessage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-screen-md px-lg py-2xl">
      <h1 className="text-lg font-semibold text-primary">{title}</h1>
      <p className="mt-sm text-sm text-secondary">{children}</p>
    </div>
  );
}
