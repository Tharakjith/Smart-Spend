import * as React from "react";
import { money } from "@/lib/format";

const reduceMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * A money amount that counts up to its value when it appears or changes. The animation is display-only:
 * the last frame shows the exact formatted value, and screen readers only ever get the exact value.
 */
export function CountUp({ value, currency, duration = 700 }: { value: string | number | null | undefined; currency: string; duration?: number }) {
  const target = value === null || value === undefined || value === "" ? null : Number(value);
  const [shown, setShown] = React.useState<number | null>(reduceMotion() ? target : 0);
  const from = React.useRef(0);

  React.useEffect(() => {
    if (target === null || !Number.isFinite(target) || reduceMotion()) {
      setShown(target);
      return;
    }
    const start = performance.now();
    const begin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(begin + (target - begin) * eased);
      if (p < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      from.current = target;
    };
  }, [target, duration]);

  const exact = money(value, currency);
  const done = shown === target;
  return (
    <>
      <span aria-hidden>{done || shown === null ? exact : money(shown, currency)}</span>
      <span className="sr-only">{exact}</span>
    </>
  );
}
