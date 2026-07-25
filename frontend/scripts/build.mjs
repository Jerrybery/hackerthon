import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const dist = join(root, "dist");
const required = ["index.html", "src/main.js", "src/styles.css"];
const threeBuildDir = join(root, "node_modules/three/build");
const threeModule = join(threeBuildDir, "three.module.js");

for (const path of required) {
  if (!existsSync(join(root, path))) {
    throw new Error(`Missing required frontend file: ${path}`);
  }
}

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

// Copy index.html with path rewrite for static hosting (Vercel excludes node_modules)
const indexContent = readFileSync(join(root, "index.html"), "utf-8")
  .replace("/node_modules/three/build/three.module.js", "/vendor/three.module.js");
writeFileSync(join(dist, "index.html"), indexContent, "utf-8");

cpSync(join(root, "src"), join(dist, "src"), { recursive: true });

if (existsSync(join(root, "public"))) {
  cpSync(join(root, "public"), join(dist, "public"), { recursive: true });
}

// Copy the entire three build directory so relative imports (e.g. ./three.core.js) resolve
const threeTarget = join(dist, "vendor");
cpSync(threeBuildDir, threeTarget, { recursive: true });

console.log("Static build prepared in dist/");
