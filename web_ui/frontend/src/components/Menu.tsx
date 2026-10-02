import React, { cloneElement, useEffect, useRef, useState } from 'react';

interface MenuProps extends React.HTMLAttributes<HTMLDivElement> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Trigger element; Menu injects aria-haspopup/aria-expanded, click handling stays on the trigger. */
  trigger: React.ReactElement;
  /** Pop direction: 'down' opens below the trigger (origin top), 'up' opens above (origin bottom). */
  side?: 'down' | 'up';
  /** Extra classes for the absolutely-positioned animated panel wrapper. */
  panelClassName?: string;
  children: React.ReactNode;
}

/**
 * Popover menu primitive (classic Apple feel):
 * - click-triggered only (no hover-open: dead on touch, accidental on desktop)
 * - Esc / outside pointerdown closes
 * - enter animation 150ms var(--ease-apple): opacity 0 -> 1 + scale .96 -> 1,
 *   transform-origin follows the pop direction; reduced motion degrades to a plain fade
 * - callers put the visual card (with the global .shadow-float token class) in children
 */
export const Menu: React.FC<MenuProps> = ({
  open,
  onOpenChange,
  trigger,
  side = 'down',
  panelClassName = '',
  className = '',
  children,
  ...rest
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  // Drives the enter transition: the panel mounts at opacity 0 / scale .96,
  // then flips to its final state on the next frame.
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    if (!open) {
      setEntered(false);
      return;
    }
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) onOpenChange(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onOpenChange]);

  const triggerEl = cloneElement(trigger as React.ReactElement<Record<string, unknown>>, {
    'aria-haspopup': 'menu',
    'aria-expanded': open,
  });

  return (
    <div ref={rootRef} className={className} {...rest}>
      {triggerEl}
      {open && (
        <div
          className={`absolute z-50 ${side === 'up' ? 'origin-bottom' : 'origin-top'} transition duration-150 ease-[var(--ease-apple)] ${
            entered ? 'opacity-100 scale-100' : 'opacity-0 scale-[.96] motion-reduce:scale-100'
          } ${panelClassName}`}
        >
          {children}
        </div>
      )}
    </div>
  );
};
