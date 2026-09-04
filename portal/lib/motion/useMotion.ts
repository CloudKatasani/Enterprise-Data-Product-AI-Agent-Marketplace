'use client';

import { useEffect, useRef, useState } from 'react';

import { motion, type MotionRegistration, type PauseReason } from './controller';

/**
 * Register an element with the global controller for the life of a component.
 *
 * The builder is held in a ref so a re-render does not deregister and
 * re-register the animation, which would restart it and, on the ribbon, jump
 * the track back to its start.
 */
export function useMotionRegistration(
  build: () => MotionRegistration | null,
  deps: readonly unknown[],
): void {
  const built = useRef(build);
  built.current = build;

  useEffect(() => {
    const registration = built.current();
    if (!registration) return undefined;
    return motion.register(registration);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Why ambient motion is currently held, for surfaces that say so. */
export function usePauseReasons(): PauseReason[] {
  const [reasons, setReasons] = useState<PauseReason[]>([]);
  useEffect(() => motion.subscribe(setReasons), []);
  return reasons;
}
