import { copyFile, mkdir, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const assetsRoot = resolve(import.meta.dirname, "..");
const source = resolve(assetsRoot, "src/app.js");
const destination = resolve(assetsRoot, "../app/web/static/js/app.js");

const metadata = await stat(source);
if (!metadata.isFile()) {
  throw new Error("Expected application JavaScript is missing: src/app.js");
}
await mkdir(dirname(destination), { recursive: true });
await copyFile(source, destination);
