export const ACCEPTED_TYPES = "image/jpeg,image/png,image/webp";
const MAX_EDGE = 2560;

export interface PendingPhoto {
  key: string;
  file: File;
  caption: string;
}

/**
 * Shrinks a phone photo to at most 2560 px and re-encodes it as JPEG before upload: smaller
 * uploads on site connections, and the browser drops EXIF (including GPS) on the way. The server
 * checks and re-encodes again, so this is a convenience, not a control. Anything the browser
 * cannot decode is sent as it is and the server decides.
 */
export async function prepareImage(file: File): Promise<Blob> {
  if (typeof createImageBitmap !== "function" || typeof document === "undefined") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", 0.85);
    });
    return blob ?? file;
  } catch {
    return file;
  }
}

export interface PendingPhoto {
  key: string;
  file: File;
  caption: string;
}
