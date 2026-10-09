import { afterEach, describe, expect, it, vi } from "vitest";

import { blobToDataUrl } from "../../lib/files";
import { prepareImage } from "./images";

const photo = () => new File([new Uint8Array([0xff, 0xd8, 0xff])], "site.jpg", { type: "image/jpeg" });

/** jsdom has no canvas: stand in for getContext and toBlob, recording the size and format used. */
function stubCanvas(result: Blob | null, context: object | null = { drawImage: vi.fn() }) {
  const canvas = { width: 0, height: 0, lastCall: null as { type: string; quality: number } | null };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => context as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (
    this: HTMLCanvasElement,
    done: BlobCallback,
    type?: string,
    quality?: number,
  ) {
    canvas.width = this.width;
    canvas.height = this.height;
    canvas.lastCall = { type: type ?? "", quality: quality ?? 0 };
    done(result);
  });
  return canvas;
}

describe("prepareImage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends the original when the browser cannot decode images", async () => {
    vi.stubGlobal("createImageBitmap", undefined);
    const file = photo();

    expect(await prepareImage(file)).toBe(file);
  });

  it("scales large photos down to 2560 px and re-encodes them as JPEG", async () => {
    const close = vi.fn();
    vi.stubGlobal("createImageBitmap", vi.fn(() => Promise.resolve({ width: 5120, height: 3840, close })));
    const encoded = new Blob(["jpeg"], { type: "image/jpeg" });
    const canvas = stubCanvas(encoded);

    const result = await prepareImage(photo());

    expect(result).toBe(encoded);
    expect([canvas.width, canvas.height]).toEqual([2560, 1920]);
    expect(canvas.lastCall).toEqual({ type: "image/jpeg", quality: 0.85 });
    expect(close).toHaveBeenCalled();
  });

  it("keeps small photos at their size", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn(() => Promise.resolve({ width: 800, height: 600, close: vi.fn() })));
    const canvas = stubCanvas(new Blob(["jpeg"]));

    await prepareImage(photo());

    expect([canvas.width, canvas.height]).toEqual([800, 600]);
  });

  it("falls back to the original when decoding or encoding fails", async () => {
    const file = photo();
    vi.stubGlobal("createImageBitmap", vi.fn(() => Promise.reject(new Error("HEIC not supported"))));
    expect(await prepareImage(file)).toBe(file);

    vi.stubGlobal("createImageBitmap", vi.fn(() => Promise.resolve({ width: 10, height: 10, close: vi.fn() })));
    stubCanvas(null);
    expect(await prepareImage(file)).toBe(file);

    vi.restoreAllMocks();
    stubCanvas(null, null);
    expect(await prepareImage(file)).toBe(file);
  });
});

describe("blobToDataUrl", () => {
  it("reads a blob as a data URL", async () => {
    expect(await blobToDataUrl(new Blob(["hi"], { type: "text/plain" }))).toBe("data:text/plain;base64,aGk=");
  });
});
