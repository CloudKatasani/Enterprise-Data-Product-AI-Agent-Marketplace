/**
 * The single global motion controller (BUILD.md 13.1).
 *
 * Components register with it; no component starts its own animation loop. That
 * is not a tidiness preference. Every pause trigger in section 13.1 — reduced
 * motion, a hidden tab, Save-Data, a low battery, a small viewport, the user's
 * own control — has to hold for *all* ambient motion at once, and a page where
 * each component decides for itself is a page where one of them is still moving
 * when the rest have stopped.
 *
 * On pause the controller calls `renderStatic()` rather than simply stopping.
 * A frozen mid-transition frame is a bug that looks like a rendering fault; a
 * composed static frame is the same information without the movement, which is
 * what reduced-motion users are owed and what everyone gets on a dead battery.
 *
 * Off-screen registrations schedule zero frames. An IntersectionObserver takes
 * them out of the loop entirely rather than ticking them into a hidden box.
 */

export type MotionClass = 'ambient' | 'reactive' | 'narrative';

export interface MotionRegistration {
  id: string;
  klass: MotionClass;
  el: HTMLElement;
  /** Called once when the element first becomes eligible to move. */
  start(): void;
  pause(): void;
  resume(): void;
  /** Compose the frame that carries the same information without movement. */
  renderStatic(): void;
  /** Optional per-frame work. Omit for animations driven by the Web Animations API. */
  tick?(elapsedMs: number): void;
}

/** Why ambient motion is currently stopped. Surfaced so the UI can say so. */
export type PauseReason =
  | 'reduced-motion'
  | 'hidden'
  | 'save-data'
  | 'battery'
  | 'viewport'
  | 'user';

export const STORAGE_KEY = 'marketplace:reduce-motion';

const REASONS: PauseReason[] = [
  'reduced-motion',
  'hidden',
  'save-data',
  'battery',
  'viewport',
  'user',
];

interface Entry {
  registration: MotionRegistration;
  visible: boolean;
  started: boolean;
  running: boolean;
}

type Listener = (reasons: PauseReason[]) => void;

/** Read a motion token off the document, so no number is chosen in TypeScript. */
export function motionToken(name: string, fallback: number): number {
  if (typeof window === 'undefined') return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

class MotionController {
  private entries = new Map<string, Entry>();

  private listeners = new Set<Listener>();

  private reasons = new Set<PauseReason>();

  private observer: IntersectionObserver | null = null;

  private frame: number | null = null;

  private lastFrame = 0;

  private started = false;

  /** Every reason ambient motion is currently held, in a stable order. */
  get pausedFor(): PauseReason[] {
    return REASONS.filter((reason) => this.reasons.has(reason));
  }

  get paused(): boolean {
    return this.reasons.size > 0;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.pausedFor);
    return () => {
      this.listeners.delete(listener);
    };
  }

  register(registration: MotionRegistration): () => void {
    this.ensureStarted();
    const entry: Entry = { registration, visible: false, started: false, running: false };
    this.entries.set(registration.id, entry);
    this.observer?.observe(registration.el);
    // Compose the static frame immediately. The element must carry its
    // information before it is ever allowed to move, which is also what keeps
    // CLS at zero: nothing appears late.
    registration.renderStatic();
    this.evaluate(entry);
    return () => {
      this.observer?.unobserve(registration.el);
      this.entries.delete(registration.id);
      this.stopLoopIfIdle();
    };
  }

  /** The user's own control. Persisted, and it outranks everything permissive. */
  setUserPreference(reduce: boolean): void {
    this.set('user', reduce);
    try {
      window.localStorage.setItem(STORAGE_KEY, reduce ? 'reduce' : 'allow');
    } catch {
      // A browser refusing storage is not a reason to refuse the preference for
      // this visit; it only means it will not be remembered for the next one.
    }
  }

  get userPrefersReduced(): boolean {
    return this.reasons.has('user');
  }

  private ensureStarted(): void {
    if (this.started || typeof window === 'undefined') return;
    this.started = true;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    this.set('reduced-motion', reduced.matches);
    reduced.addEventListener('change', (event) => this.set('reduced-motion', event.matches));

    const narrow = window.matchMedia(
      `(max-width: ${motionToken('--motion-viewport-floor-px', 0)}px)`,
    );
    this.set('viewport', narrow.matches);
    narrow.addEventListener('change', (event) => this.set('viewport', event.matches));

    document.addEventListener('visibilitychange', () =>
      this.set('hidden', document.hidden),
    );
    this.set('hidden', document.hidden);

    // Save-Data reaches the client as a connection hint rather than a header.
    const connection = (navigator as { connection?: { saveData?: boolean } }).connection;
    this.set('save-data', connection?.saveData === true);

    void this.watchBattery();

    try {
      this.set('user', window.localStorage.getItem(STORAGE_KEY) === 'reduce');
    } catch {
      this.set('user', false);
    }

    this.observer = new IntersectionObserver((records) => {
      for (const record of records) {
        const entry = [...this.entries.values()].find(
          (candidate) => candidate.registration.el === record.target,
        );
        if (!entry) continue;
        entry.visible = record.isIntersecting;
        this.evaluate(entry);
      }
    });
  }

  private async watchBattery(): Promise<void> {
    const api = (navigator as {
      getBattery?: () => Promise<{ level: number; addEventListener: (
        type: string, handler: () => void) => void }>;
    }).getBattery;
    if (!api) return;
    try {
      const battery = await api.call(navigator);
      const floor = motionToken('--motion-battery-floor', 0);
      const check = () => this.set('battery', battery.level < floor);
      battery.addEventListener('levelchange', check);
      check();
    } catch {
      // No battery API, or permission refused. Absence of a low battery is not
      // evidence of one, so motion continues.
    }
  }

  private set(reason: PauseReason, active: boolean): void {
    const had = this.reasons.has(reason);
    if (had === active) return;
    if (active) this.reasons.add(reason);
    else this.reasons.delete(reason);
    for (const entry of this.entries.values()) this.evaluate(entry);
    for (const listener of this.listeners) listener(this.pausedFor);
  }

  /**
   * Decide one registration's state.
   *
   * Reactive and narrative motion is input-driven and survives an ambient
   * pause; only `prefers-reduced-motion` and the user's own control stop it,
   * because those are statements about what the person wants rather than about
   * what the device can afford.
   */
  private evaluate(entry: Entry): void {
    const { registration } = entry;
    const stopped =
      registration.klass === 'ambient'
        ? this.paused
        : this.reasons.has('reduced-motion') || this.reasons.has('user');

    if (!entry.visible || stopped) {
      if (entry.running) {
        registration.pause();
        registration.renderStatic();
        entry.running = false;
      }
      this.stopLoopIfIdle();
      return;
    }

    if (!entry.started) {
      registration.start();
      entry.started = true;
      entry.running = true;
    } else if (!entry.running) {
      registration.resume();
      entry.running = true;
    }
    this.startLoopIfNeeded();
  }

  private startLoopIfNeeded(): void {
    if (this.frame !== null) return;
    const ticking = [...this.entries.values()].some(
      (entry) => entry.running && entry.registration.tick,
    );
    if (!ticking) return;
    this.lastFrame = performance.now();
    this.frame = requestAnimationFrame(this.step);
  }

  private stopLoopIfIdle(): void {
    if (this.frame === null) return;
    const ticking = [...this.entries.values()].some(
      (entry) => entry.running && entry.registration.tick,
    );
    if (ticking) return;
    cancelAnimationFrame(this.frame);
    this.frame = null;
  }

  private step = (now: number): void => {
    const elapsed = now - this.lastFrame;
    this.lastFrame = now;
    for (const entry of this.entries.values()) {
      if (entry.running) entry.registration.tick?.(elapsed);
    }
    this.frame = requestAnimationFrame(this.step);
  };
}

export const motion = new MotionController();
