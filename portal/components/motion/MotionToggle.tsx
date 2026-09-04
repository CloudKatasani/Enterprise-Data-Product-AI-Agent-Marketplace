'use client';

import { useEffect, useState } from 'react';

import { motion } from '@/lib/motion/controller';
import { usePauseReasons } from '@/lib/motion/useMotion';

/**
 * The global reduce-motion control (13.1).
 *
 * It is a persisted user preference, not a session toggle, and it is stated in
 * words rather than an icon: a visitor who needs it should not have to guess
 * which glyph means "stop moving". When something other than the visitor has
 * already stopped ambient motion — a hidden tab, a low battery, a small screen,
 * the operating system's own setting — the control says which, because a
 * toggle that appears to do nothing is worse than one that explains itself.
 */
const WORDING: Record<string, string> = {
  'reduced-motion': 'your system setting',
  hidden: 'this tab being in the background',
  'save-data': 'your data-saver setting',
  battery: 'a low battery',
  viewport: 'a narrow screen',
  user: 'your choice',
};

export function MotionToggle() {
  const reasons = usePauseReasons();
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(motion.userPrefersReduced);
  }, [reasons]);

  const others = reasons.filter((reason) => reason !== 'user');

  return (
    <div className="motion-toggle">
      <button
        type="button"
        aria-pressed={reduced}
        onClick={() => {
          motion.setUserPreference(!reduced);
          setReduced(!reduced);
        }}
        className="motion-toggle-button"
      >
        {reduced ? 'Allow motion' : 'Reduce motion'}
      </button>
      {others.length > 0 ? (
        <p className="motion-toggle-note">
          Ambient motion is already paused because of{' '}
          {others.map((reason) => WORDING[reason] ?? reason).join(' and ')}.
        </p>
      ) : null}
    </div>
  );
}
