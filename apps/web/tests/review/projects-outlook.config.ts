/** Isolated synthetic review harness; never starts the application or a source adapter. */
import path from "node:path";
import { defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";

const root = path.resolve(import.meta.dirname, "../..");
export default defineConfig({
  root,
  base: "./",
  build: {
    outDir: "build/projects-outlook-review",
    rollupOptions: { input: path.join(root, "tests/review/projects-outlook.html") },
  },
  define: { "process.env": "{}" },
  plugins: [tsconfigPaths({ projects: [path.join(root, "tsconfig.json")] })],
  resolve: {
    alias: {
      "@/hooks/store/user": path.join(root, "tests/review/projects-outlook-stubs.ts"),
      "@/hooks/use-curve-projects": path.join(root, "tests/review/projects-outlook-stubs.ts"),
      "next/link": path.join(root, "app/compat/next/link.tsx"),
      "next/navigation": path.join(root, "app/compat/next/navigation.ts"),
    },
    dedupe: ["react", "react-dom"],
  },
  server: { host: "127.0.0.1", port: 4317, strictPort: true },
});
