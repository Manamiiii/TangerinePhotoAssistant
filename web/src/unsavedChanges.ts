import { useEffect, useRef } from "react";

export function createUnsavedRegistry() {
  const entries = new Map<object, { dirty: boolean; saving: boolean }>();
  return {
    set(key: object, dirty: boolean, saving: boolean) { entries.set(key, { dirty, saving }); },
    remove(key: object) { entries.delete(key); },
    hasChanges() { return [...entries.values()].some((entry) => entry.dirty || entry.saving); },
    canLeave(confirm: (message: string) => boolean, notify: (message: string) => void) {
      if ([...entries.values()].some((entry) => entry.saving)) {
        notify("正在保存，请等待保存结束后再离开。");
        return false;
      }
      return ![...entries.values()].some((entry) => entry.dirty)
        || confirm("还有未保存的修改，确定放弃并离开吗？");
    },
  };
}

const registry = createUnsavedRegistry();
export const confirmLeave = () => registry.canLeave((message) => window.confirm(message), (message) => window.alert(message));

export function useUnsavedChanges(dirty: boolean, saving = false) {
  const key = useRef({});
  useEffect(() => {
    const id = key.current;
    registry.set(id, dirty, saving);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!registry.hasChanges()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => { registry.remove(id); window.removeEventListener("beforeunload", beforeUnload); };
  }, [dirty, saving]);
}
