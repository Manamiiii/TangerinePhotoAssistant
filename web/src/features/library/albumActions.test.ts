import { beforeEach, describe, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { createAlbumActions } from "./albumActions";

vi.mock("../../api", () => ({ getJson: vi.fn() }));

function setup() {
  const dependencies = {
    setError: vi.fn(), setEvents: vi.fn(), setAlbumOffset: vi.fn(),
    invalidate: vi.fn(), refreshLibrary: vi.fn().mockResolvedValue(undefined), pushToast: vi.fn(),
  };
  return { ...dependencies, ...createAlbumActions(dependencies) };
}

describe("album actions", () => {
  beforeEach(() => vi.resetAllMocks());

  it("resets pagination and refreshes related resources only after successful creation", async () => {
    const actions = setup();
    vi.mocked(getJson).mockRejectedValueOnce(new Error("创建失败"));
    expect(await actions.createAlbum("生日", "纪念")).toBeNull();
    expect(actions.setAlbumOffset).not.toHaveBeenCalled();
    expect(actions.refreshLibrary).not.toHaveBeenCalled();
    expect(actions.setError).toHaveBeenLastCalledWith("创建失败");
    vi.mocked(getJson).mockResolvedValueOnce({ id: 42 });
    expect(await actions.createAlbum("生日", "纪念")).toBe(42);
    expect(actions.setAlbumOffset).toHaveBeenCalledWith(0);
    expect(actions.refreshLibrary).toHaveBeenCalledWith("albums");
  });

  it("propagates failed assignment to keep the caller's selection available for retry", async () => {
    const actions = setup();
    const failure = new Error("不能移动部分连拍成员");
    vi.mocked(getJson).mockRejectedValueOnce(failure);
    await expect(actions.assignToAlbum(7, [1, 2])).rejects.toBe(failure);
    expect(actions.setError).toHaveBeenLastCalledWith(failure.message);
    expect(actions.refreshLibrary).not.toHaveBeenCalled();
    expect(actions.pushToast).not.toHaveBeenCalled();
  });

  it("refreshes assignment resources before announcing success", async () => {
    const actions = setup();
    vi.mocked(getJson).mockResolvedValue({});
    let finishRefresh!: () => void;
    actions.refreshLibrary.mockImplementation(() => new Promise<void>((resolve) => { finishRefresh = resolve; }));
    const assigning = actions.assignToAlbum(7, [1, 2]);
    await Promise.resolve();
    expect(actions.pushToast).not.toHaveBeenCalled();
    finishRefresh();
    await assigning;
    expect(actions.pushToast).toHaveBeenCalledWith("success", "已将 2 张照片归入目标相册");
  });

  it("encodes category names containing path delimiters", async () => {
    const actions = setup();
    vi.mocked(getJson).mockResolvedValue({});
    await actions.renameAlbumType("旅行/纪念", "旅行");
    expect(getJson).toHaveBeenCalledWith(`/api/album-types/${encodeURIComponent("旅行/纪念")}`, expect.objectContaining({ method: "PUT" }));
    expect(actions.refreshLibrary).toHaveBeenCalledWith("albums");
  });
});
