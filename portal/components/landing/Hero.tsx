'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Constellation } from '@/components/landing/Constellation';
import { motionToken } from '@/lib/motion/controller';
import { MotionToggle } from '@/components/motion/MotionToggle';
import type { AnswerPulse, HeroBand } from '@/lib/types';

/**
 * The hero (band 1).
 *
 * The constellation behind the copy is the estate itself — real identifiers,
 * real edges, coordinates the server settled. It sits under a scrim that
 * guarantees the headline's contrast whatever the graph happens to look like,
 * and CI asserts that contrast on the rendered page rather than trusting the
 * token.
 *
 * Answer pulses arrive over the event stream. They are capped by the API at the
 * motion layer's rate, and the client keeps only the most recent few: a pulse
 * two minutes after its answer would be saying something untrue about when it
 * happened, and a queue is how that happens.
 */
export function Hero({
  hero,
  searchExamples,
}: {
  hero: HeroBand;
  searchExamples: string[];
}) {
  const pulses = useAnswerPulses();
  const [placeholder, setPlaceholder] = useState(searchExamples[0] ?? '');

  useEffect(() => {
    if (searchExamples.length === 0) return undefined;
    let index = 0;
    const timer = window.setInterval(() => {
      index = (index + 1) % searchExamples.length;
      setPlaceholder(searchExamples[index] ?? '');
    }, motionToken('--hero-placeholder-rotate-ms', 0));
    return () => window.clearInterval(timer);
  }, [searchExamples]);

  return (
    <section className="hero">
      <Constellation hero={hero} pulses={pulses} />
      <div className="hero-scrim" aria-hidden />
      <div className="hero-copy">
        <h1 className="hero-headline">
          Every governed data product and AI agent in the enterprise — on one shelf.
        </h1>
        <p className="hero-sub">
          Find it, watch it answer, request it, use it today — with the contract, the
          quality score, the entitlement and the value case attached to each one.
        </p>

        <form action="/discover" method="get" className="hero-search" role="search">
          <label htmlFor="hero-q" className="sr-only">
            Search the catalog
          </label>
          <input
            id="hero-q"
            name="q"
            type="search"
            className="hero-input"
            placeholder={placeholder}
            autoComplete="off"
          />
          <button type="submit" className="hero-search-button">
            Search
          </button>
        </form>

        <div className="hero-actions">
          <Link href="/data-products" className="hero-cta-primary">
            Browse the catalog
          </Link>
          <Link href="#theatre-heading" className="hero-cta-ghost">
            Watch an agent answer
          </Link>
        </div>

        <MotionToggle />
      </div>
    </section>
  );
}

/**
 * Subscribe to the answer stream.
 *
 * A stream that goes quiet sends heartbeats, so a dead channel is
 * distinguishable from a quiet estate; on a dead one the pulses simply stop and
 * the constellation keeps its settled frame. Nothing here retries in a loop —
 * `EventSource` reconnects on its own, and a second reconnection loop on top of
 * it is how a page ends up hammering an endpoint that is down.
 */
function useAnswerPulses(): AnswerPulse[] {
  const [pulses, setPulses] = useState<AnswerPulse[]>([]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') return undefined;
    const source = new EventSource('/api/events');
    source.addEventListener('pulse', (event) => {
      try {
        const pulse = JSON.parse((event as MessageEvent).data) as AnswerPulse;
        setPulses((current) => [...current, pulse].slice(-keepOnScreen()));
      } catch {
        // A frame we cannot parse is a frame we do not animate.
      }
    });
    return () => source.close();
  }, []);

  return pulses;
}

/**
 * How many pulses stay on screen at once.
 *
 * Derived rather than chosen: at the cap of pulses per second, and with each
 * pulse lasting its own duration, this is exactly how many can be in flight.
 * Keeping more would mean holding one after it had finished animating.
 */
function keepOnScreen(): number {
  const rate = motionToken('--constellation-pulse-rate-max', 0);
  const duration = motionToken('--constellation-pulse-ms', 0);
  const perSecond = motionToken('--motion-second-ms', 1);
  return Math.max(Math.ceil((rate * duration) / perSecond), 1);
}
