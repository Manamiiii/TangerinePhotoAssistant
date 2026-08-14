import type { ReactNode } from "react";

export function ModalShell({ title, close, children, wide = false }: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={close}>
    <section className={`editor-modal ${wide ? "wide" : ""}`} onClick={(event) => event.stopPropagation()}>
      <header><h3>{title}</h3><button onClick={close} aria-label="关闭">×</button></header>
      {children}
    </section>
  </div>;
}
