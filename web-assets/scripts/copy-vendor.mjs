import { copyFile, mkdir, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const assetsRoot = resolve(import.meta.dirname, "..");
const vendorRoot = resolve(assetsRoot, "../app/web/static/vendor");
const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/@alpinejs/csp/dist/cdn.min.js", "alpine-csp.min.js"],
];

await mkdir(vendorRoot, { recursive: true });
for (const [sourceRelativePath, destinationName] of files) {
  const source = resolve(assetsRoot, sourceRelativePath);
  const destination = resolve(vendorRoot, destinationName);
  try {
    const metadata = await stat(source);
    if (!metadata.isFile()) {
      throw new Error("is not a file");
    }
  } catch (error) {
    throw new Error(`Expected vendor asset is missing: ${sourceRelativePath}`, { cause: error });
  }
  await mkdir(dirname(destination), { recursive: true });
  await copyFile(source, destination);
}
