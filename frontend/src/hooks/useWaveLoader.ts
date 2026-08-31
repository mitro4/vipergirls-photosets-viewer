import { useCallback, useEffect, useRef, useState } from "react";

/** Maximum image slots per card (cover + 4 previews). */
export const MAX_SLOTS = 5;
/** Total wave steps: MAX_SLOTS for thumbs + MAX_SLOTS for mediums. */
const TOTAL_STEPS = 2 * MAX_SLOTS;
/** Per-step safety timeout: auto-advance if a step stalls (broken images). */
const WAVE_TIMEOUT_MS = 8_000;
/**
 * Fraction of cards that must complete a slot before the wave advances.
 * Waiting for ALL cards lets one dead host stall every card on the page;
 * a 90% quorum (ceil, min 1) advances while the stragglers catch up async.
 */
const QUORUM = 0.9;

function quorumCount(numCards: number): number {
  if (numCards <= 0) return 0;
  return Math.max(1, Math.ceil(numCards * QUORUM));
}

/**
 * Wave-based image loading coordinator.
 *
 * Orchestrates progressive image loading across ALL cards on the page:
 *
 * - **Phase 1 (thumb):** slot 0 of every card loads in parallel → slot 1 of
 *   every card → … → slot N-1. Within a single card, thumbs load strictly
 *   sequentially (slot *i* starts only after slot *i-1* completes).
 *
 * - **Phase 2 (medium):** the same wave pattern repeats for medium-quality
 *   variants. When a medium finishes downloading for a card, that card's
 *   visible `<img>` swaps from thumb → medium (served instantly from browser
 *   cache).
 *
 * The coordinator advances `step` once a **quorum** (90%) of participating
 * cards reports completion for the current slot (via `reportCardDone`);
 * cards with fewer than `MAX_SLOTS` images auto-complete the missing slots.
 * A straggler on a dead host no longer stalls the entire page.
 *
 * @param numCards  Number of cards participating in the wave.
 * @param enabled   Wave runs only when `true`. Set to `false` while cover
 *                  metadata is still loading; the wave resets and starts
 *                  fresh when this flips to `true`.
 */
export function useWaveLoader(numCards: number, enabled: boolean) {
  const [step, setStep] = useState(0);
  const completedRef = useRef<Set<number>>(new Set());

  // Stable refs so `reportCardDone` identity never changes (avoids re-running
  // effects in every ThreadCard on every coordinator state change).
  const enabledRef = useRef(enabled);
  const numCardsRef = useRef(numCards);
  enabledRef.current = enabled;
  numCardsRef.current = numCards;

  // Reset whenever the wave is (re)started — page nav, sort change, or covers
  // finishing their batch fetch.  Both transitions (false→true and true→false)
  // reset to step 0.
  useEffect(() => {
    setStep(0);
    completedRef.current = new Set();
  }, [enabled, numCards]);

  const reportCardDone = useCallback((cardIdx: number) => {
    if (!enabledRef.current || numCardsRef.current === 0) return;
    if (completedRef.current.has(cardIdx)) return;
    completedRef.current.add(cardIdx);
    if (completedRef.current.size >= quorumCount(numCardsRef.current)) {
      completedRef.current = new Set();
      setStep((s) => Math.min(s + 1, TOTAL_STEPS));
    }
  }, []);

  // Safety net: if a step stalls (e.g. an image host is permanently down and
  // the circuit breaker hasn't tripped yet, or a probe's onload/onerror never
  // fires), auto-advance so the whole page doesn't hang on one slot.
  useEffect(() => {
    if (!enabled || step >= TOTAL_STEPS) return;
    const t = setTimeout(() => {
      completedRef.current = new Set();
      setStep((s) => Math.min(s + 1, TOTAL_STEPS));
    }, WAVE_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [enabled, step]);

  return { step, reportCardDone };
}
