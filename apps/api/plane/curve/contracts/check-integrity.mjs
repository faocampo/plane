import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const repositoryRoot = new URL("../../../../../", import.meta.url);
const contextPath = new URL("apps/api/plane/curve/contracts/m0-s2-context.json", repositoryRoot);
const m003ContextPath = new URL("apps/api/plane/curve/contracts/m0-03-context.json", repositoryRoot);
const m0s3ContextPath = new URL("apps/api/plane/curve/contracts/m0-s3-context.json", repositoryRoot);
const m0s4ContextPath = new URL("apps/api/plane/curve/contracts/m0-s4-context.json", repositoryRoot);
const temporalSupplyChainPath = new URL("apps/api/plane/curve/contracts/temporal-supply-chain.json", repositoryRoot);
const openapiDirectory = new URL("apps/api/plane/curve/contracts/openapi/", repositoryRoot);
const schemaDirectory = new URL("apps/api/plane/curve/contracts/schemas/", repositoryRoot);
const policyDirectory = new URL("apps/api/plane/curve/contracts/policy/", repositoryRoot);

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

const expectedM003Context = {
  curveRevision: "097016ffe2eb259cc780ad2a6cd41ca3422366b2",
  planeBaseRevision: "eff8686a69aa112ea8fda79be0e1316dc1fd97d6",
  contextDigest: "sha256:113fcd3cf9795585a5db5a59e5d21965dd4e6ba9525fe5ea9d3bd4b15e546359",
};

const expectedM003Files = {
  "contracts/policy/core-policy-v1.json": "e0c4a03e27fd2b53b0109856c1599804865469ebebfc480244f4e76f7653cc52",
  "contracts/schemas/core-policy-manifest.schema.json":
    "bdc10bd52e9189a6d1994248bb791b07c5011eeb1c3ffc668ba44bf8d523f46f",
  "contracts/schemas/policy-evaluation.schema.json": "75622a18bbbdaa69795beee16254106f12aab2aa150e1619f237d3bf67d724f8",
  "contracts/schemas/policy-decision.schema.json": "5faa121136c59420da7fb1582985c3d445b6486e1e52a77c8d6ff853634f4bd8",
};

const expectedM0S3Context = {
  curveRevision: "aece53943525c6e7f7993551453954fe27b00746",
  planeBaseRevision: "922dd6de5d5ed5081f35cd88343154022867ccad",
  contextDigest: "sha256:0edadab2d51b7898ed91b556ea3f072f4127b909d0755bd7d5993597fe618f26",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
};

const expectedM0S3Files = {
  "contracts/policy/core-policy-v1.json": "e0c4a03e27fd2b53b0109856c1599804865469ebebfc480244f4e76f7653cc52",
  "contracts/schemas/audit-event.schema.json": "36fcb1f4023cc26619f5e20bf78670e83b2bf4bb48112fdaca1481daa84157f1",
  "contracts/schemas/common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
  "contracts/schemas/event-envelope.schema.json": "de28a9654520b2f27d307b246a48f4d6b847e924d53e1d95513c47c29c5166ed",
  "contracts/schemas/idempotency-record.schema.json":
    "9c40ad05af41e89d1fa8890550f03591c106070337c2cf5ff091aedd74210801",
  "contracts/schemas/inbox-message.schema.json": "e1b06e1cb5ea157e2249014229dceac3c1ea0f07bda393a2832ba886dcd84527",
  "contracts/schemas/operation-event-v1.schema.json":
    "fdba17d38e5e930b9abca6ceae47a7dd7b33c4bdd88b5e740e684c89548315d0",
  "contracts/schemas/operation.schema.json": "887c0d1e9b667f61db66834efdcafc72f581e71641a66e0bfa4006661bbb9aff",
  "contracts/schemas/outbox-event.schema.json": "fd5db47b56f359eb7333e06c0c7ec1f9f90b00a6b4b07f791f10d0177cc79711",
  "contracts/schemas/policy-decision.schema.json": "5faa121136c59420da7fb1582985c3d445b6486e1e52a77c8d6ff853634f4bd8",
  "contracts/schemas/policy-evaluation.schema.json": "75622a18bbbdaa69795beee16254106f12aab2aa150e1619f237d3bf67d724f8",
};

const expectedM0S4Context = {
  curveRevision: "79c7cd6cced82f8f3dede6cbad2706ae3d7befb8",
  approvedProductRevision: "42ea32981a3d5ce814a74c18e458ac8152a7e2fa",
  planeBaseRevision: "d99342f589db4eb488695487d3ae3f2c16bf0874",
  contextDigest: "sha256:79cf9f3c0267c4a42f7142aa457ac1e086c8a990a41e20703729d0aa9cca1bf3",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
};

const expectedM0S4VendoredFiles = {
  "contracts/openapi/curve-v1.openapi.yaml": "8ee9dc46de9cec7a7cd88d4a4b923221900f7a046e367f73fde0328df850c54a",
  "contracts/policy/core-policy-v1.json": "e0c4a03e27fd2b53b0109856c1599804865469ebebfc480244f4e76f7653cc52",
  "contracts/schemas/common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
  "contracts/schemas/event-envelope.schema.json": "de28a9654520b2f27d307b246a48f4d6b847e924d53e1d95513c47c29c5166ed",
  "contracts/schemas/operation-event-v1.schema.json":
    "fdba17d38e5e930b9abca6ceae47a7dd7b33c4bdd88b5e740e684c89548315d0",
  "contracts/schemas/operation-summary.schema.json": "3a237b4f66a90b92545446989da0678b0e82f0f19aa2a9a4bf159740dfa80bb1",
  "contracts/schemas/operation.schema.json": "887c0d1e9b667f61db66834efdcafc72f581e71641a66e0bfa4006661bbb9aff",
  "contracts/schemas/sse-event.schema.json": "58270829c666d40307c168c7e7852e3b23e5a37548ad85a10948bc9d4d548c80",
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

const m003Context = JSON.parse(await readFile(m003ContextPath, "utf8"));
if (m003Context.curve_revision !== expectedM003Context.curveRevision) {
  fail("unexpected M0-03 Curve revision");
}
if (m003Context.plane_base_revision !== expectedM003Context.planeBaseRevision) {
  fail("unexpected M0-03 Plane base revision");
}
if (m003Context.context_digest !== expectedM003Context.contextDigest) {
  fail("unexpected M0-03 context-pack digest");
}
if (!Array.isArray(m003Context.files) || !Array.isArray(m003Context.paths)) {
  fail("M0-03 context paths and per-file digests are required");
}
if (JSON.stringify(m003Context.paths) !== JSON.stringify([...m003Context.paths].toSorted())) {
  fail("M0-03 context paths are not sorted");
}

const recordedM003Digests = new Map(m003Context.files.map(({ path, sha256: digest }) => [path, digest]));
await Promise.all(
  Object.entries(expectedM003Files).map(async ([sourcePath, expectedDigest]) => {
    const fileName = sourcePath.split("/").at(-1);
    const directory = sourcePath.includes("/policy/") ? policyDirectory : schemaDirectory;
    const bytes = await readFile(new URL(fileName, directory));
    const observedDigest = sha256(bytes);
    if (observedDigest !== expectedDigest) {
      fail(`${fileName} digest ${observedDigest} does not match ${expectedDigest}`);
    }
    if (recordedM003Digests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-03 context manifest`);
    }
    if (!m003Context.paths.includes(sourcePath)) {
      fail(`${sourcePath} is absent from the M0-03 context path set`);
    }
  })
);

console.log(
  `Curve M0-S2 contract integrity passed: ${Object.keys(expectedSchemaDigests).length} schemas at ${expectedContext.curveRevision}`
);
console.log(
  `Curve M0-03 contract integrity passed: ${Object.keys(expectedM003Files).length} files at ${expectedM003Context.curveRevision}`
);

const m0s3Context = JSON.parse(await readFile(m0s3ContextPath, "utf8"));
if (m0s3Context.schema_version !== "curve-context-pack/v1" || m0s3Context.task_id !== "M0-S3") {
  fail("unexpected M0-S3 context identity");
}
if (m0s3Context.curve_revision !== expectedM0S3Context.curveRevision) {
  fail("unexpected M0-S3 Curve revision");
}
if (m0s3Context.plane_base_revision !== expectedM0S3Context.planeBaseRevision) {
  fail("unexpected M0-S3 Plane base revision");
}
if (m0s3Context.context_digest !== expectedM0S3Context.contextDigest) {
  fail("unexpected M0-S3 context-pack digest");
}
if (
  m0s3Context.human_owner !== expectedM0S3Context.owner ||
  m0s3Context.human_reviewer !== expectedM0S3Context.reviewer ||
  m0s3Context.data_classification !== "INTERNAL"
) {
  fail("unexpected M0-S3 ownership or data classification");
}
if (!Array.isArray(m0s3Context.files) || !Array.isArray(m0s3Context.paths)) {
  fail("M0-S3 context paths and per-file digests are required");
}
if (JSON.stringify(m0s3Context.paths) !== JSON.stringify([...m0s3Context.paths].toSorted())) {
  fail("M0-S3 context paths are not sorted");
}
if (JSON.stringify(m0s3Context.files.map(({ path }) => path)) !== JSON.stringify(m0s3Context.paths)) {
  fail("M0-S3 context files and paths differ");
}
if (new Set(m0s3Context.paths).size !== m0s3Context.paths.length) {
  fail("M0-S3 context paths are not unique");
}
for (const file of m0s3Context.files) {
  if (!/^sha256:[0-9a-f]{64}$/.test(file.sha256)) {
    fail(`M0-S3 context digest is invalid for ${file.path}`);
  }
}

const recordedM0S3Digests = new Map(m0s3Context.files.map(({ path, sha256: digest }) => [path, digest]));
await Promise.all(
  Object.entries(expectedM0S3Files).map(async ([sourcePath, expectedDigest]) => {
    const fileName = sourcePath.split("/").at(-1);
    const directory = sourcePath.includes("/policy/") ? policyDirectory : schemaDirectory;
    const observedDigest = sha256(await readFile(new URL(fileName, directory)));
    if (observedDigest !== expectedDigest) {
      fail(`${fileName} digest ${observedDigest} does not match M0-S3 source ${expectedDigest}`);
    }
    if (recordedM0S3Digests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-S3 context manifest`);
    }
  })
);

console.log(
  `Curve M0-S3 context integrity passed: ${m0s3Context.paths.length} files at ${expectedM0S3Context.curveRevision}`
);

const m0s4Context = JSON.parse(await readFile(m0s4ContextPath, "utf8"));
if (m0s4Context.schema_version !== "curve-context-pack/v1" || m0s4Context.task_id !== "M0-S4") {
  fail("unexpected M0-S4 context identity");
}
if (
  m0s4Context.curve_revision !== expectedM0S4Context.curveRevision ||
  m0s4Context.approved_product_revision !== expectedM0S4Context.approvedProductRevision ||
  m0s4Context.plane_base_revision !== expectedM0S4Context.planeBaseRevision ||
  m0s4Context.context_digest !== expectedM0S4Context.contextDigest
) {
  fail("unexpected M0-S4 revision or context digest");
}
if (
  m0s4Context.human_owner !== expectedM0S4Context.owner ||
  m0s4Context.human_reviewer !== expectedM0S4Context.reviewer ||
  m0s4Context.data_classification !== "INTERNAL" ||
  m0s4Context.execution_scope !== "LOCAL_ONLY"
) {
  fail("unexpected M0-S4 ownership, classification, or execution scope");
}
if (
  m0s4Context.approval_evidence?.curve_pr !== "https://github.com/faocampo/curve/pull/17" ||
  m0s4Context.approval_evidence?.approved_head !== "a4638761bcbdb8e522e8db0af5a2ae00cb6480a8" ||
  m0s4Context.approval_evidence?.squash_commit !== expectedM0S4Context.approvedProductRevision ||
  JSON.stringify(m0s4Context.approval_evidence?.ux_records) !== JSON.stringify(["UX-004-M0-S4", "UX-005-M0-S4"])
) {
  fail("unexpected M0-S4 approval evidence");
}
if (
  m0s4Context.planning_reconciliation?.curve_pr !== "https://github.com/faocampo/curve/pull/18" ||
  m0s4Context.planning_reconciliation?.revision !== expectedM0S4Context.curveRevision ||
  m0s4Context.planning_reconciliation?.state !== "DRAFT_PENDING_HUMAN_REVIEW"
) {
  fail("unexpected M0-S4 planning reconciliation state");
}
if (!Array.isArray(m0s4Context.files) || !Array.isArray(m0s4Context.paths)) {
  fail("M0-S4 context paths and per-file digests are required");
}
if (JSON.stringify(m0s4Context.paths) !== JSON.stringify([...m0s4Context.paths].toSorted())) {
  fail("M0-S4 context paths are not sorted");
}
if (JSON.stringify(m0s4Context.files.map(({ path }) => path)) !== JSON.stringify(m0s4Context.paths)) {
  fail("M0-S4 context files and paths differ");
}
if (new Set(m0s4Context.paths).size !== m0s4Context.paths.length) {
  fail("M0-S4 context paths are not unique");
}
for (const file of m0s4Context.files) {
  if (!/^sha256:[0-9a-f]{64}$/.test(file.sha256)) {
    fail(`M0-S4 context digest is invalid for ${file.path}`);
  }
}

const recordedM0S4Digests = new Map(m0s4Context.files.map(({ path, sha256: digest }) => [path, digest]));
await Promise.all(
  Object.entries(expectedM0S4VendoredFiles).map(async ([sourcePath, expectedDigest]) => {
    const fileName = sourcePath.split("/").at(-1);
    const directory = sourcePath.includes("/openapi/")
      ? openapiDirectory
      : sourcePath.includes("/policy/")
        ? policyDirectory
        : schemaDirectory;
    const observedDigest = sha256(await readFile(new URL(fileName, directory)));
    if (observedDigest !== expectedDigest) {
      fail(`${sourcePath} digest ${observedDigest} does not match M0-S4 source ${expectedDigest}`);
    }
    if (recordedM0S4Digests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-S4 context manifest`);
    }
  })
);

console.log(
  `Curve M0-S4 context integrity passed: ${m0s4Context.paths.length} files at ${expectedM0S4Context.curveRevision}`
);

const temporalSupplyChain = JSON.parse(await readFile(temporalSupplyChainPath, "utf8"));
if (
  temporalSupplyChain.schema_version !== "curve-temporal-supply-chain/v1" ||
  temporalSupplyChain.scope !== "D-003_LOCAL_ONLY" ||
  temporalSupplyChain.package?.name !== "temporalio" ||
  temporalSupplyChain.package?.version !== "1.31.0" ||
  temporalSupplyChain.package?.license_expression !== "MIT" ||
  temporalSupplyChain.package?.requires_python !== ">=3.10" ||
  temporalSupplyChain.server?.embedded_server_version !== "1.31.2" ||
  temporalSupplyChain.server?.license_expression !== "MIT" ||
  temporalSupplyChain.server?.image !==
    "docker.io/temporalio/temporal:1.8.1@sha256:59561b9ef060eaeb1f46cb6a1842d6cbdd8a393eb3b6d315ecef5fe2f0b1d7a6"
) {
  fail("unexpected Temporal supply-chain identity");
}
const expectedTemporalWheels = new Map([
  [
    "musllinux_1_2_aarch64",
    {
      filename: "temporalio-1.31.0-cp310-abi3-musllinux_1_2_aarch64.whl",
      digest: "sha256:f23f36d0e5d2e67f2129fc1cb876cf1e4e614f791a717d692f7c15fb732abe41",
    },
  ],
  [
    "musllinux_1_2_x86_64",
    {
      filename: "temporalio-1.31.0-cp310-abi3-musllinux_1_2_x86_64.whl",
      digest: "sha256:52f8cc7f0b5a19d49f0c2d748420267aaacc2be0bb614743de8d10faf77a57c9",
    },
  ],
]);
for (const wheel of temporalSupplyChain.package.wheels ?? []) {
  const expectedWheel = expectedTemporalWheels.get(wheel.platform);
  if (!expectedWheel || expectedWheel.filename !== wheel.filename || expectedWheel.digest !== wheel.sha256) {
    fail(`unexpected Temporal wheel digest for ${wheel.platform}`);
  }
  expectedTemporalWheels.delete(wheel.platform);
}
if (expectedTemporalWheels.size !== 0) fail("required Temporal wheel metadata is missing");

console.log("Curve Temporal supply-chain integrity passed: temporalio 1.31.0 / server 1.31.2");
