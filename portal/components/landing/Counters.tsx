'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';

import { motionToken } from '@/lib/motion/controller';
import { useMotionRegistration } from '@/lib/motion/useMotion';
import type { LandingCounter } from '@/lib/types';

/**
 * The trust strip (13.5, band 2).
 *
 * Four numbers read from the platform, each linking to the filtered view it
 * counts. A counter a visitor cannot click through to is a claim they cannot
 * check, and every number on this page is meant to be checkable.
 *
 * They count up once, on first viewport entry. The static equivalent is the
 * final value — which is the information; the count-up was only ever the way it
 * arrived.
 */
export function Counters({ counters }: { counters: LandingCounter[] }) {
  return (
    <section className="counters" aria-label="The estate, live">
      <ul className="counter-strip" role="list">
        {counters.map((counter) => (
          <li key={counter.code}>
            <Link href={counter.href} className="counter">
              <CountUp value={counter.value} code={counter.code} />
              <span className="counter-label">{counter.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CountUp({ value, code }: { value: number; code: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [shown, setShown] = useState(value);

  useMotionRegistration(() => {
    const element = ref.current;
    if (!element) return null;
    let elapsed = 0;
    const duration = motionToken('--counter-count-up-ms', 0);
    let done = false;

    return {
      id: `counter-${code}`,
      klass: 'narrative' as const,
      el: element,
      start() {
        elapsed = 0;
        done = false;
        setShown(0);
      },
      pause() {},
      resume() {},
      renderStatic() {
        done = true;
        setShown(value);
      },
      tick(sinceLastFrame: number) {
        if (done) return;
        elapsed += sinceLastFrame;
        if (elapsed >= duration || duration <= 0) {
          done = true;
          setShown(value);
          return;
        }
        setShown(Math.round((elapsed / duration) * value));
      },
    };
  }, [value, code]);

  return (
    <span ref={ref} className="counter-value tabular-nums">
      {shown.toLocaleString()}
    </span>
  );
}
