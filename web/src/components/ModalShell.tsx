import { manageDialogFocus } from "./dialogFocus";
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
    const modal = modalRef.current;
    if (!modal) return;
    const release = manageDialogFocus(modal);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || Array.from(document.querySelectorAll('[aria-modal="true"]')).at(-1) !== modal) return;
      event.preventDefault();
      closeRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); release(); };
  }, []);
  return <div className="editor-backdrop" onClick={close}>
    <section ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={`editor-modal ${wide ? "wide" : ""}`} onClick={(event) => event.stopPropagation()}>
      <header><h3>{title}</h3><button onClick={close} aria-label="关闭">×</button></header>
      {children}
    </section>
  </div>;
}
