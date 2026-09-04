'use client';

import { useRef } from 'react';

import { motionToken } from '@/lib/motion/controller';
import { useMotionRegistration } from '@/lib/motion/useMotion';
import type { TickerEvent } from '@/lib/types';

/**
 * The activity ticker (13.5).
 *
 * A slow vertical crawl of anonymised statements about the estate. Never a
 * person, never an asset above Internal, never an event derived from fewer
 * occurrences than the rubric's floor — all three are enforced by the API,
 * which is the only place they can be enforced honestly. This component's job
 * is the second rule: **if the channel is down, hide**. A frozen stale ticker
 * claims a liveness it does not have, and that is worse than an absent band.
 *
 * The crawl is one transform on one list. Under reduced motion the same
 * statements are simply a list, which is what they were all along.
 */
export function ActivityTicker({ events, live }: { events: TickerEvent[]; live: boolean }) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const animation = useRef<Animation | null>(null);

  useMotionRegistration(() => {
    const track = trackRef.current;
    if (!track) return null;
    return {
      id: 'activity-ticker',
      klass: 'ambient' as const,
      el: track,
      start() {
        const height = track.scrollHeight / COPIES.length;
        const speed = motionToken('--ticker-crawl-speed', 0);
        if (height <= 0 || speed <= 0) return;
        animation.current = track.animate(
          [
            { transform: 'translate3d(0,0,0)' },
            { transform: `translate3d(0,${-height}px,0)` },
          ],
          {
            duration: (height / speed) * motionToken('--motion-second-ms', 1),
            iterations: Infinity,
            easing: 'linear',
          },
        );
      },
      pause() {
        animation.current?.pause();
      },
      resume() {
        animation.current?.play();
      },
      renderStatic() {
        animation.current?.cancel();
        animation.current = null;
        track.style.transform = 'translate3d(0,0,0)';
      },
    };
  }, [events.length]);

  if (!live || events.length === 0) return null;

  return (
    <section className="ticker" aria-label="Recent activity">
      <div className="ticker-viewport">
        <div className="ticker-track" ref={trackRef}>
          {COPIES.map((copy) => (
            <ul key={copy} className="ticker-list" role="list" aria-hidden={copy === 'seam'}>
              {events.map((event) => (
                <li key={`${copy}-${event.code}-${event.text}`} className="ticker-item">
                  {event.text}
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>
    </section>
  );
}

/** As on the ribbon: the duplicate is what makes the loop seamless. */
const COPIES = ['primary', 'seam'] as const;
