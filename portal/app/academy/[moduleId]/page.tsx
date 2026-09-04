import Link from 'next/link';

import { PageMessage } from '@/components/ui/PageMessage';
import { apiTry } from '@/lib/api';
import type { AcademyModule } from '@/lib/types';

export const dynamic = 'force-dynamic';

const PARAGRAPH_BREAK = /\n\s*\n/;

/**
 * One academy module.
 *
 * (Called `lesson` in this file: `module` is a reserved identifier in a Next.js
 * page, and the alternative to renaming it was disabling the rule that says so.)
 *
 * The body is Markdown-ish prose from the manifest the module was seeded from —
 * one copy of every sentence the academy teaches, so a change to it arrives as
 * a diff. Rendering is deliberately plain: paragraphs and emphasis, no embedded
 * HTML, because content that can carry markup is content that can carry script.
 *
 * The sandbox link is what makes this a lesson rather than a page. Section 20.2
 * asks for modules that run against the demo tier, so every module ends at a
 * place where the reader does the thing.
 */
export default async function ModulePage({
  params,
}: {
  params: Promise<{ moduleId: string }>;
}) {
  const { moduleId } = await params;
  const result = await apiTry<AcademyModule>(`/academy/modules/${moduleId}`);

  if (!result.ok) {
    return <PageMessage title="Module">{result.problem.detail}</PageMessage>;
  }

  const lesson = result.data;
  // A blank line separates paragraphs, which is the only structure a module
  // body has and the only structure this page renders.
  const paragraphs = (lesson.body ?? '').split(PARAGRAPH_BREAK).filter(Boolean);

  return (
    <div className="mx-auto max-w-screen-2xl px-lg py-xl">
      <nav aria-label="Breadcrumb" className="mb-md text-2xs text-muted">
        <Link href="/academy" className="hover:underline">
          Academy
        </Link>
        {lesson.path_id ? ` · ${lesson.path_id}` : null}
      </nav>

      <article className="module">
        <h1 className="text-xl font-semibold text-primary">{lesson.title}</h1>
        <p className="mt-3xs text-2xs uppercase tracking-wide text-muted">
          {lesson.estimated_minutes} minutes
          {lesson.sandbox_tier ? ` · sandbox on the ${lesson.sandbox_tier} tier` : ''}
        </p>
        <p className="mt-2xs max-w-prose text-sm text-secondary">{lesson.summary}</p>

        <div className="module-body">
          {paragraphs.map((paragraph, index) => (
            <Prose key={index} text={paragraph} />
          ))}
        </div>

        {lesson.sandbox_tier ? (
          <aside className="module-sandbox">
            <h2 className="refusal-subhead">Try it</h2>
            <p className="mt-2xs text-sm text-secondary">
              Everything in this module works on the demo tier: synthetic data in a
              separate schema on the same code path, so a query you write here runs
              unchanged against production once your grant lands.
            </p>
            <div className="mt-2xs flex flex-wrap gap-sm">
              <Link href="/discover" className="module-link">
                Search the catalog
              </Link>
              <Link href="/agents" className="module-link">
                Ask an agent
              </Link>
            </div>
          </aside>
        ) : null}
      </article>
    </div>
  );
}

/**
 * A paragraph, with `**bold**` and `*emphasis*` honoured and nothing else.
 *
 * Deliberately not a Markdown renderer. Module bodies are trusted content from
 * the repository, but the smallest renderer that reads well is still the right
 * one: anything that interprets raw HTML is a place where a future untrusted
 * body would become a script tag.
 */
function Prose({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean);
  return (
    <p>
      {parts.map((part, index) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={index} className="font-semibold">
              {part.slice('**'.length, -'**'.length)}
            </strong>
          );
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code key={index} className="module-code">
              {part.slice('`'.length, -'`'.length)}
            </code>
          );
        }
        if (part.startsWith('*') && part.endsWith('*')) {
          return <em key={index}>{part.slice('*'.length, -'*'.length)}</em>;
        }
        return <span key={index}>{part}</span>;
      })}
    </p>
  );
}
