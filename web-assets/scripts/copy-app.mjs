import { copyFile, mkdir, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const assetsRoot = resolve(import.meta.dirname, "..");
const assets = ["app.js", "google-sign-in.js"];

for (const asset of assets) {
  const source = resolve(assetsRoot, "src", asset);
  const destination = resolve(assetsRoot, "../app/web/static/js", asset);
  const metadata = await stat(source);
  if (!metadata.isFile()) {
    throw new Error(`Expected application JavaScript is missing: src/${asset}`);
  }
  await mkdir(dirname(destination), { recursive: true });
  await copyFile(source, destination);
}
