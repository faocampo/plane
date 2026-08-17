import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const repositoryRoot = new URL("../../../../../", import.meta.url);
const contextPath = new URL("apps/api/plane/curve/contracts/m0-s2-context.json", repositoryRoot);
const schemaDirectory = new URL("apps/api/plane/curve/contracts/schemas/", repositoryRoot);

const expectedContext = {
  curveRevision: "ab2c81a33ede719c02ff0a2a6ab35eabcf304de1",
  planeBaseRevision: "7685bbc7cc5e1ab34f11e3912d9e47d31c365a9a",
  contextDigest: "sha256:45c266e1ab0d096747d6493a828d689251584bad70a1570582478bfe1a91cedc",
};

const expectedSchemaDigests = {
  "audit-event.schema.json": "36fcb1f4023cc26619f5e20bf78670e83b2bf4bb48112fdaca1481daa84157f1",
  "common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
  "event-envelope.schema.json": "de28a9654520b2f27d307b246a48f4d6b847e924d53e1d95513c47c29c5166ed",
  "idempotency-record.schema.json": "9c40ad05af41e89d1fa8890550f03591c106070337c2cf5ff091aedd74210801",
  "inbox-message.schema.json": "e1b06e1cb5ea157e2249014229dceac3c1ea0f07bda393a2832ba886dcd84527",
  "operation-event-v1.schema.json": "fdba17d38e5e930b9abca6ceae47a7dd7b33c4bdd88b5e740e684c89548315d0",
  "operation.schema.json": "887c0d1e9b667f61db66834efdcafc72f581e71641a66e0bfa4006661bbb9aff",
  "outbox-event.schema.json": "fd5db47b56f359eb7333e06c0c7ec1f9f90b00a6b4b07f791f10d0177cc79711",
};

const fail = (message) => {
  throw new Error(`Curve contract integrity check failed: ${message}`);
};

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

const context = JSON.parse(await readFile(contextPath, "utf8"));
if (context.curve_revision !== expectedContext.curveRevision) fail("unexpected Curve revision");
if (context.plane_base_revision !== expectedContext.planeBaseRevision) fail("unexpected Plane base revision");
if (context.context_digest !== expectedContext.contextDigest) fail("unexpected context-pack digest");

await Promise.all(
  Object.entries(expectedSchemaDigests).map(async ([schemaName, expectedDigest]) => {
    const bytes = await readFile(new URL(schemaName, schemaDirectory));
    const observedDigest = sha256(bytes);
    if (observedDigest !== expectedDigest) {
      fail(`${schemaName} digest ${observedDigest} does not match ${expectedDigest}`);
    }

    const schema = JSON.parse(bytes.toString("utf8"));
    const expectedId = `https://curve.x3m.internal/contracts/schemas/${schemaName}`;
    if (schema.$schema !== "https://json-schema.org/draft/2020-12/schema") {
      fail(`${schemaName} does not declare JSON Schema 2020-12`);
    }
    if (schema.$id !== expectedId) fail(`${schemaName} has unexpected $id ${schema.$id}`);
    if (!context.paths.includes(`contracts/schemas/${schemaName}`)) {
      fail(`${schemaName} is absent from the pinned context path set`);
    }
  })
);

console.log(
  `Curve M0-S2 contract integrity passed: ${Object.keys(expectedSchemaDigests).length} schemas at ${expectedContext.curveRevision}`
);
