/** Local source-imported service checks; no account or network access. */
import { fileURLToPath } from "node:url";
export default {
  resolve: {
    alias: { vitest: fileURLToPath(new URL("../../../apps/web/node_modules/vitest/dist/index.js", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["packages/services/tests/project-association-preconditions.test.ts"],
  },
};
