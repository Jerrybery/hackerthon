import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const dist = join(root, "dist");
const required = ["index.html", "src/main.js", "src/styles.css"];
const threeModule = join(root, "node_modules/three/build/three.module.js");

for (const path of required) {
  if (!existsSync(join(root, path))) {
    throw new Error(`Missing required frontend file: ${path}`);
  }
}

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
cpSync(join(root, "index.html"), join(dist, "index.html"));
cpSync(join(root, "src"), join(dist, "src"), { recursive: true });

if (existsSync(join(root, "public"))) {
  cpSync(join(root, "public"), join(dist, "public"), { recursive: true });
}

const threeTarget = join(dist, "node_modules/three/build");
mkdirSync(threeTarget, { recursive: true });
cpSync(threeModule, join(threeTarget, "three.module.js"));

console.log("Static build prepared in dist/");
