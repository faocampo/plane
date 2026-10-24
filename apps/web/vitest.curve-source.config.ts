import path from "node:path";
import { defineConfig, mergeConfig } from "vitest/config";
import base from "./vitest.config";
export default mergeConfig(
  base,
  defineConfig({
    resolve: {
      alias: {
        "@plane/services": path.resolve(__dirname, "../../packages/services/src/index.ts"),
      },
    },
  })
);
