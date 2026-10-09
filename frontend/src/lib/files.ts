/** A blob as a data: URL (photo display without object URLs to revoke). */
export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("Could not read the file."));
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("Could not read the file."));
    };
    reader.readAsDataURL(blob);
  });
}
