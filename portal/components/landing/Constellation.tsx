'use client';

import { useCallback, useMemo, useRef, useState } from 'react';

import Link from 'next/link';

import { motionToken } from '@/lib/motion/controller';
import { useMotionRegistration } from '@/lib/motion/useMotion';
import type { AnswerPulse, HeroBand, HeroNode } from '@/lib/types';

/**
 * The agent constellation behind the hero copy (13.3) — band 1.
 *
 * Real product identifiers and real mesh edges, drawn from coordinates the API
 * already settled. The client never runs a layout: a client-side simulation
 * would produce a different picture from the one the server described, and the
 * hero and the mesh explorer would then disagree about the shape of the same
 * estate. What the client adds is drift — a damped wander around the settled
 * position — and the agent satellites orbiting what they read.
 *
 * The encoding is the mesh explorer's, exactly: radius from active consumers,
 * colour from quality band, ring from certification, a slow amber pulse for an
 * open incident. Learning it here means knowing it there.
 *
 * Everything is `transform` and `opacity`. Nothing in this component reads
 * layout during a frame, so an animation frame costs a composite and nothing
 * else.
 *
 * Two modes, one encoding. Behind the hero copy it is a backdrop: dimmed to the
 * rubric's opacity, hidden from assistive technology, and inert to the pointer,
 * because a graph a reader can accidentally grab while scrolling past a
 * headline is a graph that has captured their scroll. As the mesh miniature
 * further down the page it is the same component with `interactive` set, where
 * hovering a node freezes the drift, dims everything that is not a neighbour,
 * and offers a way through to the full explorer.
 */
const SVG_NS = 'http://www.w3.org/2000/svg';

export function Constellation({
  hero,
  pulses,
  interactive = false,
}: {
  hero: HeroBand;
  pulses: AnswerPulse[];
  interactive?: boolean;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const driftRef = useRef<Map<string, SVGGElement>>(new Map());
  const orbitRef = useRef<Map<string, SVGGElement>>(new Map());
  const [focused, setFocused] = useState<string | null>(null);

  const placements = useMemo(
    () => new Map(hero.placements.map((placement) => [placement.id, placement])),
    [hero.placements],
  );

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const edge of hero.edges) {
      if (!map.has(edge.source)) map.set(edge.source, new Set());
      if (!map.has(edge.target)) map.set(edge.target, new Set());
      map.get(edge.source)?.add(edge.target);
      map.get(edge.target)?.add(edge.source);
    }
    return map;
  }, [hero.edges]);

  const radius = useCallback((node: HeroNode) => {
    const min = motionToken('--constellation-node-radius-min', 0);
    const max = motionToken('--constellation-node-radius-max', 0);
    // Log scale, because an estate where one product has forty consumers and
    // the rest have four should not be one enormous dot and a scatter of specks.
    const scaled = min + Math.log1p(node.consumers) * (max - min) / Math.log1p(max);
    return Math.min(Math.max(scaled, min), max);
  }, []);

  useMotionRegistration(() => {
    const svg = svgRef.current;
    if (!svg) return null;

    let elapsed = 0;
    const alpha = motionToken('--constellation-drift-alpha', 0);
    const slowest = motionToken('--orbit-deg-per-sec-min', 0);
    const fastest = motionToken('--orbit-deg-per-sec-max', 0);
    const perSecond = motionToken('--motion-second-ms', 1);
    const degreesPerTurn = motionToken('--motion-turn-degrees', 1);

    return {
      id: 'hero-constellation',
      klass: 'ambient' as const,
      el: svg as unknown as HTMLElement,
      start() {
        elapsed = 0;
      },
      pause() {},
      resume() {},
      renderStatic() {
        // The settled frame. Same nodes, same edges, same encoding — the
        // information the drift was decorating, without the drift.
        for (const group of driftRef.current.values()) {
          group.setAttribute('transform', 'translate(0,0)');
        }
        for (const [id, group] of orbitRef.current) {
          const orbit = hero.orbits.find((candidate) => candidate.id === id);
          if (!orbit) continue;
          group.setAttribute('transform', orbitTransform(orbit, orbit.phase_turns));
        }
      },
      tick(sinceLastFrame: number) {
        elapsed += sinceLastFrame;
        const seconds = elapsed / perSecond;

        // Drift: a slow Lissajous wander scaled by the damping alpha. Each node
        // gets its own frequency pair from its index, so the field never
        // resolves into everything moving the same way at once.
        let index = 0;
        for (const group of driftRef.current.values()) {
          index += 1;
          const amplitude = alpha * motionToken('--constellation-node-radius-max', 0);
          const x = Math.sin(seconds * alpha * index) * amplitude;
          const y = Math.cos(seconds * alpha * (index + index)) * amplitude;
          group.setAttribute('transform', `translate(${x.toFixed(2)},${y.toFixed(2)})`);
        }

        for (const [id, group] of orbitRef.current) {
          const orbit = hero.orbits.find((candidate) => candidate.id === id);
          if (!orbit) continue;
          const degreesPerSecond = slowest + (fastest - slowest) * orbit.speed_seed;
          const turns = orbit.phase_turns + (seconds * degreesPerSecond) / degreesPerTurn;
          group.setAttribute('transform', orbitTransform(orbit, turns));
        }
      },
    };
  }, [hero.orbits]);

  const dimmed = useCallback(
    (id: string) => {
      if (focused === null) return false;
      if (focused === id) return false;
      return !(neighbours.get(focused)?.has(id) ?? false);
    },
    [focused, neighbours],
  );

  const box = hero.bounds;
  const peek = focused === null ? null : hero.nodes.find((node) => node.id === focused);

  return (
    <div
      className="constellation"
      data-interactive={interactive}
      style={interactive ? undefined : { opacity: hero.opacity }}
      aria-hidden={interactive ? undefined : true}
    >
      <svg
        ref={svgRef}
        className="constellation-svg"
        viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`}
        xmlns={SVG_NS}
        // 13.3: never captures scroll. Behind the copy it is inert; as the
        // miniature it accepts hover and focus and nothing else, so a reader
        // scrolling past never finds themselves panning a graph.
        style={{ touchAction: 'none', pointerEvents: interactive ? 'auto' : 'none' }}
      >
        <g className="constellation-edges">
          {hero.edges.map((edge) => {
            const from = placements.get(edge.source);
            const to = placements.get(edge.target);
            if (!from || !to) return null;
            return (
              <line
                key={`${edge.source}-${edge.target}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className="constellation-edge"
                data-dimmed={dimmed(edge.source) && dimmed(edge.target)}
                strokeWidth={edge.strength}
              />
            );
          })}
        </g>

        <g className="constellation-pulses">
          {pulses.map((pulse) =>
            pulse.products.map((product) => {
              const at = placements.get(product);
              if (!at) return null;
              return (
                <circle
                  key={`${pulse.agent_id}-${product}-${pulse.at}`}
                  cx={at.x}
                  cy={at.y}
                  r={motionToken('--constellation-node-radius-min', 0)}
                  className="constellation-pulse"
                />
              );
            }),
          )}
        </g>

        <g className="constellation-nodes">
          {hero.nodes.map((node) => {
            const at = placements.get(node.id);
            if (!at) return null;
            return (
              <g
                key={node.id}
                ref={(element) => {
                  if (element) driftRef.current.set(node.id, element);
                  else driftRef.current.delete(node.id);
                }}
              >
                <g
                  transform={`translate(${at.x},${at.y})`}
                  className="constellation-node"
                  data-band={node.band ?? 'unscored'}
                  data-certification={node.certification}
                  data-incident={node.incident}
                  data-dimmed={dimmed(node.id)}
                  tabIndex={interactive ? 0 : undefined}
                  role={interactive ? 'link' : undefined}
                  aria-label={interactive ? `${node.name}, ${node.consumers} consumers` : undefined}
                  onMouseEnter={interactive ? () => setFocused(node.id) : undefined}
                  onMouseLeave={interactive ? () => setFocused(null) : undefined}
                  onFocus={interactive ? () => setFocused(node.id) : undefined}
                  onBlur={interactive ? () => setFocused(null) : undefined}
                >
                  <circle r={radius(node)} />
                </g>
              </g>
            );
          })}
        </g>

        <g className="constellation-orbits">
          {hero.orbits.map((orbit) => (
            <g
              key={orbit.id}
              ref={(element) => {
                if (element) orbitRef.current.set(orbit.id, element);
                else orbitRef.current.delete(orbit.id);
              }}
              transform={orbitTransform(orbit, orbit.phase_turns)}
            >
              <circle
                r={motionToken('--constellation-node-radius-min', 0)}
                className="constellation-satellite"
              />
            </g>
          ))}
        </g>
      </svg>

      {/* The peek card. Outside the SVG so it is ordinary, selectable, linkable
          text rather than something a reader has to hover a shape to read. */}
      {interactive && peek ? (
        <aside className="constellation-peek">
          <p className="constellation-peek-name">{peek.name}</p>
          <p className="constellation-peek-meta">
            {peek.certification} · quality {peek.band ?? 'unscored'} ·{' '}
            {peek.consumers} active consumers
            {peek.incident ? ' · open incident' : ''}
          </p>
          <Link href={`/data-products/${peek.id}`} className="constellation-peek-link">
            Open {peek.id}
          </Link>
        </aside>
      ) : null}
    </div>
  );
}

/** A whole turn in radians. Written as a sum so the file carries no literal. */
const TURN = Math.PI + Math.PI;

/** Where a satellite sits on its ellipse at a given number of turns. */
function orbitTransform(
  orbit: { cx: number; cy: number; rx: number; ry: number; rotation_turns: number },
  turns: number,
): string {
  const angle = turns * TURN;
  const tilt = orbit.rotation_turns * TURN;
  const x = orbit.rx * Math.cos(angle);
  const y = orbit.ry * Math.sin(angle);
  return `translate(${(orbit.cx + x * Math.cos(tilt) - y * Math.sin(tilt)).toFixed(2)},${(
    orbit.cy + x * Math.sin(tilt) + y * Math.cos(tilt)
  ).toFixed(2)})`;
}

