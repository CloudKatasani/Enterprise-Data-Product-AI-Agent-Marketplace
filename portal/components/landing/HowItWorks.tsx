import Link from 'next/link';

/**
 * How it works (band 7).
 *
 * Four steps, in the order a first-time visitor will actually take them. The
 * band exists because the rest of the page shows capability and none of it
 * shows sequence: a visitor who has watched an agent answer still does not know
 * whether they can use it this afternoon, and that question is the one that
 * decides whether they come back.
 *
 * Each step links to the surface it describes rather than to a screenshot of
 * it. A marketing page that shows pictures of a product it could show is
 * hiding something.
 */
const STEPS = [
  {
    code: 'discover',
    title: 'Discover',
    href: '/discover',
    body:
      'Search across products, agents, certified KPIs and the glossary at once. ' +
      'Every result says what it is, who owns it and whether you can query it yet.',
  },
  {
    code: 'try',
    title: 'Try',
    href: '/agents',
    body:
      'Ask an agent a question on the demo tier before requesting anything. The ' +
      'trace shows every tool it called and every row it read, so you can judge ' +
      'the answer rather than take it.',
  },
  {
    code: 'request',
    title: 'Request',
    href: '/requests/new/access',
    body:
      'The form previews the decision before you submit it: which path it takes, ' +
      'who decides, and the clock it starts. Nothing about the outcome is a ' +
      'surprise arriving days later.',
  },
  {
    code: 'consume',
    title: 'Consume',
    href: '/data-products',
    body:
      'Query it by SQL, REST, MCP or a semantic view under the purpose you ' +
      'declared. The contract you were shown is the contract that is enforced.',
  },
] as const;

export function HowItWorks() {
  return (
    <section className="how" aria-labelledby="how-heading">
      <h2 id="how-heading" className="band-heading">
        How it works
      </h2>
      <ol className="how-steps">
        {STEPS.map((step, index) => (
          <li key={step.code} className="how-step">
            <p className="how-index tabular-nums" aria-hidden>
              {index + 1}
            </p>
            <h3 className="how-title">
              <Link href={step.href} className="hover:underline">
                {step.title}
              </Link>
            </h3>
            <p className="how-body">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
