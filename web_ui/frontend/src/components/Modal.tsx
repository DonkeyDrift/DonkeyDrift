import React, { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name of the dialog (use one of label / labelledBy). */
  label?: string;
  labelledBy?: string;
  /** Visual classes of the panel (sizing, colors, radius). */
  className?: string;
  children: React.ReactNode;
}

/**
 * Modal dialog primitive (classic Apple feel):
 * - traditional frosted scrim: bg-black/40 + backdrop-blur-sm (no Liquid Glass lensing)
 * - Esc and scrim click close
 * - focus is trapped inside (Tab / Shift+Tab wrap), initial focus moves into the
 *   dialog on open and is restored to the previously focused element on close
 * - role="dialog" aria-modal="true" on the overlay wrapper
 */
export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  label,
  labelledBy,
  className = '',
  children,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  // Keep the latest onClose without re-running the focus effect on every parent render.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const prevActive = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (first ?? panel)?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Stop nested layers (e.g. an underlying overlay) from also handling this Esc.
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      // Focus trap: wrap Tab / Shift+Tab around the focusable elements of the panel.
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstItem || !panel.contains(active))) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && (active === lastItem || !panel.contains(active))) {
        e.preventDefault();
        firstItem.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      prevActive?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={label}
      aria-labelledby={labelledBy}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div ref={panelRef} tabIndex={-1} className={`outline-none ${className}`}>
        {children}
      </div>
    </div>
  );
};
