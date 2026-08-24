import { useEffect, useRef, type ReactNode } from "react";

export function ModalShell({ title, close, children, wide = false }: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const modalRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const modal = modalRef.current;
    const focusable = () => Array.from(modal?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
    ) ?? []);
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) {
        event.preventDefault();
        modal?.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, []);
  return <div className="editor-backdrop" onClick={close}>
    <section ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={`editor-modal ${wide ? "wide" : ""}`} onClick={(event) => event.stopPropagation()}>
      <header><h3>{title}</h3><button onClick={close} aria-label="关闭">×</button></header>
      {children}
    </section>
  </div>;
}
