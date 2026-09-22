import type { Dispatch, SetStateAction } from "react";
import { getJson } from "../../api";
import type { ResourceMutation } from "../../pageResources";
import type { EventItem, EventsResponse } from "./types";

type AlbumActionDependencies = {
  setError: (message: string | null) => void;
  setEvents: Dispatch<SetStateAction<EventsResponse | null>>;
  setAlbumOffset: (offset: number) => void;
  invalidate: (mutation: ResourceMutation) => void;
  refreshLibrary: (mutation: ResourceMutation) => Promise<void>;
  pushToast: (kind: "success" | "error", message: string) => void;
};

export function createAlbumActions({
  setError, setEvents, setAlbumOffset, invalidate, refreshLibrary, pushToast,
}: AlbumActionDependencies) {
  const updateEvent = async (event: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status" | "equipment_keys" | "equipment_count">>) => {
    setError(null);
    const next = { ...event, ...changes };
    try {
      await getJson(`/api/albums/${event.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposed_name: next.proposed_name, category: next.category, status: next.status, ...(changes.equipment_keys ? { accessory_keys: changes.equipment_keys } : {}) }),
      });
      setEvents((current) => current ? { ...current, items: current.items.map((item) => item.id === event.id ? next : item) } : current);
      invalidate("albums");
      return true;
    } catch (reason) {
      setError((reason as Error).message);
      return false;
    }
  };

  const createAlbum = async (name: string, category: string): Promise<number | null> => {
    setError(null);
    try {
      const created = await getJson<{ id: number }>("/api/albums", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category }),
      });
      setAlbumOffset(0);
      await refreshLibrary("albums");
      return created.id;
    } catch (reason) {
      setError((reason as Error).message);
      return null;
    }
  };

  const createAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson("/api/album-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await refreshLibrary("albums");
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const deleteAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, { method: "DELETE" });
      await refreshLibrary("albums");
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const renameAlbumType = async (name: string, nextName: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      await refreshLibrary("albums");
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const assignToAlbum = async (albumId: number, captureIds: number[]) => {
    setError(null);
    try {
      await getJson(`/api/albums/${albumId}/captures`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds }),
      });
      await refreshLibrary("albums");
      pushToast("success", `已将 ${captureIds.length} 张照片归入目标相册`);
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  return { updateEvent, createAlbum, createAlbumType, deleteAlbumType, renameAlbumType, assignToAlbum };
}
