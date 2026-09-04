'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import Link from 'next/link';

import { ProductCard } from '@/components/catalog/ProductCard';
import { motion, motionToken } from '@/lib/motion/controller';
import { useMotionRegistration } from '@/lib/motion/useMotion';
import type { FeaturedProduct } from '@/lib/types';

const SPEED_ROW_ONE = '--ribbon-speed-row1';
const SPEED_ROW_TWO = '--ribbon-speed-row2';

/**
 * The living data product ribbon (13.2) — band 4.
 *
 * Two rows travelling in opposite directions at different speeds, so they do
 * not read as one block. Each row is **one** animation on **one** composited
 * layer, not an animation per card: sixty cards each running their own
 * transition is sixty things for the compositor to reconcile every frame, and
 * it is how a ribbon ends up dropping frames on a laptop.
 *
 * The track is duplicated once and reset at exactly one track width, so the
 * seam is invisible and there is no scroll-position hack anywhere in here.
 *
 * Pointer or keyboard focus pauses the row it is in, and leaving resumes from
 * where it stopped rather than from the start — a row that jumped back to the
 * beginning every time a reader looked away would be unusable for the one
 * thing it is for.
 *
 * Cards are the ordinary catalog card. Not a copy of it: the same component,
 * so the twelve fixed elements stay in the same twelve places on the marketing
 * surface as in the grid, and a change to one is a change to both.
 */
export function ProductRibbon({
  products,
  staticCards,
  totalProducts,
}: {
  products: FeaturedProduct[];
  staticCards: number;
  totalProducts: number;
}) {
  const [paused, setPaused] = useState(false);
  const rows = useMemo(() => split(products), [products]);

  if (products.length === 0) {
    // 13.2: with no payload the band collapses. A marketing page never renders
    // a skeleton, and an empty box that promises cards is worse than no box.
    return null;
  }

  return (
    <section className="ribbon" aria-labelledby="ribbon-heading">
      <div className="ribbon-head">
        <div>
          <h2 id="ribbon-heading" className="band-heading">
            What is on the shelf
          </h2>
          <p className="band-sub">
            Every card is the catalog card, with the same twelve elements in the same
            places. Nothing here is arranged for the front page.
          </p>
        </div>
        <button
          type="button"
          className="ribbon-control"
          aria-pressed={paused}
          onClick={() => setPaused((current) => !current)}
        >
          {paused ? 'Play' : 'Pause'}
        </button>
      </div>

      {/* The reduced-motion equivalent is always in the DOM and always
          accessible; the controller decides which one is shown, so a static
          reader and a moving one are looking at the same information. */}
      <div className="ribbon-static">
        <ul className="ribbon-grid" role="list">
          {products.slice(0, staticCards).map((product) => (
            <ProductCard key={product.product_id} product={product} />
          ))}
        </ul>
        <Link href="/data-products" className="ribbon-more">
          Browse all {totalProducts} data products
        </Link>
      </div>

      <div className="ribbon-rows">
        {rows.map((row, index) => (
          <RibbonRow
            key={index === 0 ? 'row-one' : 'row-two'}
            products={row}
            reversed={index > 0}
            speedToken={index === 0 ? SPEED_ROW_ONE : SPEED_ROW_TWO}
            paused={paused}
          />
        ))}
      </div>
    </section>
  );
}

/** Two rows of comparable length, order preserved, alternating. */
function split(products: FeaturedProduct[]): FeaturedProduct[][] {
  const first: FeaturedProduct[] = [];
  const second: FeaturedProduct[] = [];
  let toFirst = true;
  for (const product of products) {
    (toFirst ? first : second).push(product);
    toFirst = !toFirst;
  }
  return second.length > 0 ? [first, second] : [first];
}

/**
 * The track is the row, then the row again. The duplicate is what makes the
 * loop seamless: translating by exactly one copy's width returns the row to a
 * frame identical to its first, so the seam is arithmetic rather than a guess.
 */
const COPIES = ['primary', 'seam'] as const;

function RibbonRow({
  products,
  reversed,
  speedToken,
  paused,
}: {
  products: FeaturedProduct[];
  reversed: boolean;
  speedToken: string;
  paused: boolean;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const animation = useRef<Animation | null>(null);
  const hovered = useRef(false);

  const compose = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    track.style.transform = 'translate3d(0,0,0)';
  }, []);

  useMotionRegistration(() => {
    const track = trackRef.current;
    if (!track) return null;
    return {
      id: `ribbon-${speedToken}`,
      klass: 'ambient' as const,
      el: track,
      start() {
        // One animation for the whole row, on one composited layer.
        const width = track.scrollWidth / COPIES.length;
        const speed = motionToken(speedToken, 0);
        if (width <= 0 || speed <= 0) return;
        const duration = (width / speed) * motionToken('--motion-second-ms', 1);
        const from = reversed ? -width : 0;
        const to = reversed ? 0 : -width;
        animation.current = track.animate(
          [
            { transform: `translate3d(${from}px,0,0)` },
            { transform: `translate3d(${to}px,0,0)` },
          ],
          { duration, iterations: Infinity, easing: 'linear' },
        );
      },
      pause() {
        animation.current?.pause();
      },
      resume() {
        if (!hovered.current && !paused) animation.current?.play();
      },
      renderStatic() {
        animation.current?.cancel();
        animation.current = null;
        compose();
      },
    };
  }, [speedToken, reversed]);

  // Pointer and focus are input, not ambient: they pause this row only, and
  // they do it whatever the global controller has decided.
  const hold = () => {
    hovered.current = true;
    animation.current?.pause();
  };
  const release = () => {
    hovered.current = false;
    if (!paused && !motion.paused) animation.current?.play();
  };

  if (paused) animation.current?.pause();
  else if (!hovered.current && !motion.paused) animation.current?.play();

  return (
    <div
      className="ribbon-viewport"
      onMouseEnter={hold}
      onMouseLeave={release}
      onFocusCapture={hold}
      onBlurCapture={release}
    >
      <div className="ribbon-track" ref={trackRef}>
        {COPIES.map((copy) => (
          <ul
            key={copy}
            className="ribbon-list"
            role="list"
            // The seam copy is the same cards, so a screen reader announcing it
            // would be reading the shelf twice.
            aria-hidden={copy === 'seam' ? true : undefined}
          >
            {products.map((product) => (
              <ProductCard key={`${copy}-${product.product_id}`} product={product} />
            ))}
          </ul>
        ))}
      </div>
    </div>
  );
}
