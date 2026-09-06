/** Keep keyboard focus inside the topmost dialog, including after controls disappear. */
export function manageDialogFocus(dialog: HTMLElement) {
  const previous = document.activeElement as HTMLElement | null;
  const items = () => Array.from(dialog.querySelectorAll<HTMLElement>(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], summary, [tabindex]:not([tabindex="-1"])'
  )).filter((element) => element.getClientRects().length > 0 && !element.matches(":disabled") && !element.closest('[inert], [aria-hidden="true"]'));
  const topmost = () => Array.from(document.querySelectorAll('[aria-modal="true"]')).at(-1) === dialog;
  (items()[0] ?? dialog).focus({ preventScroll: true });
  const trap = (event: KeyboardEvent) => {
    if (event.key !== "Tab" || !topmost()) return;
    const controls = items();
    const index = controls.indexOf(document.activeElement as HTMLElement);
    if (!controls.length || index < 0 || (event.shiftKey ? index === 0 : index === controls.length - 1)) {
      event.preventDefault();
      (event.shiftKey ? controls.at(-1) ?? dialog : controls[0] ?? dialog).focus();
    }
  };
  document.addEventListener("keydown", trap);
  return () => {
    document.removeEventListener("keydown", trap);
    if (previous?.isConnected) previous.focus({ preventScroll: true });
  };
}

export function ignorePhotoShortcut(event: Pick<KeyboardEvent, "defaultPrevented" | "ctrlKey" | "metaKey" | "altKey" | "isComposing">, target: HTMLElement | null) {
  return event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.isComposing
    || Boolean(target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'));
}
