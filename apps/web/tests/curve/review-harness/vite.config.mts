import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";
const root = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(root, "../../..");
export default defineConfig({
  root,
  base: "./",
  publicDir: false,
  plugins: [tsconfigPaths({ projects: [path.join(web, "tsconfig.json")] })],
  define: { "process.env": "{}" },
  resolve: {
    alias: {
      "@plane/services": path.resolve(web, "../../packages/services/src/index.ts"),
      "next/link": path.join(root, "review-link.tsx"),
      "next/navigation": path.join(web, "app/compat/next/navigation.ts"),
      "next/script": path.join(web, "app/compat/next/script.tsx"),
    },
    dedupe: ["react", "react-dom", "@headlessui/react"],
  },
  build: { outDir: path.join(root, "dist"), emptyOutDir: true },
});
