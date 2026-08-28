import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const repositoryRoot = new URL("../../../../../", import.meta.url);
const contextPath = new URL("apps/api/plane/curve/contracts/m0-s2-context.json", repositoryRoot);
const m003ContextPath = new URL("apps/api/plane/curve/contracts/m0-03-context.json", repositoryRoot);
const m0s3ContextPath = new URL("apps/api/plane/curve/contracts/m0-s3-context.json", repositoryRoot);
const m0s4ContextPath = new URL("apps/api/plane/curve/contracts/m0-s4-context.json", repositoryRoot);
const m0s5ContextPath = new URL("apps/api/plane/curve/contracts/m0-s5-context.json", repositoryRoot);
const m0s5bContextPath = new URL("apps/api/plane/curve/contracts/m0-s5b-context.json", repositoryRoot);
const m0s6aContextPath = new URL("apps/api/plane/curve/contracts/m0-s6a-context.json", repositoryRoot);
const m0s9aContextPath = new URL("apps/api/plane/curve/contracts/m0-s9a-context.json", repositoryRoot);
const temporalSupplyChainPath = new URL("apps/api/plane/curve/contracts/temporal-supply-chain.json", repositoryRoot);
const openapiDirectory = new URL("apps/api/plane/curve/contracts/openapi/", repositoryRoot);
const schemaDirectory = new URL("apps/api/plane/curve/contracts/schemas/", repositoryRoot);
const semanticFixtureDirectory = new URL("apps/api/plane/curve/contracts/schemas/semantic-fixtures/", repositoryRoot);
const schemaExampleDirectory = new URL("apps/api/plane/curve/contracts/schemas/examples/", repositoryRoot);
const policyDirectory = new URL("apps/api/plane/curve/contracts/policy/", repositoryRoot);
const providerDirectory = new URL("apps/api/plane/curve/contracts/providers/", repositoryRoot);
const observabilityDirectory = new URL("apps/api/plane/curve/contracts/observability/", repositoryRoot);
const temporalDirectory = new URL("apps/api/plane/curve/contracts/temporal/", repositoryRoot);

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

const expectedM0S5Context = {
  curveRevision: "a23dab99e9afcc9dbfad7f5a3dc8b394ef60e529",
  approvedContractHead: "fa6fd677fc41d0bc73a8587e78d33d55a6824429",
  planeBaseRevision: "e762fbbd2c1726a2833745add8245a1679c60d88",
  contextDigest: "sha256:720a70bb9146761e7b4f1852e889127460812d25d84cbafd1304e20caa18ac1a",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
};

const expectedM0S5VendoredFiles = {
  "contracts/observability/m0-s5-telemetry-v1.json": "8ba95e5e605188e829df03374114eb2ec0d2cbea0218f1d286198cbbb2d34d9b",
  "contracts/schemas/operation-event-v2.schema.json":
    "3d3b67fa2939b93517f061d852f4562087db87728b66893dd05823b44881fa73",
  "contracts/schemas/telemetry-manifest.schema.json":
    "b25c1d758fa995370a01996b811770bdbd335374bda7ea88a790359d4c126942",
};

const expectedM0S5BContext = {
  curveRevision: "43480ca8463d0b40d436145aeb19fbbc8c2be472",
  approvedContractHead: "5a3ab82d7b960c862ea83c6ebf89e086be19b758",
  planeBaseRevision: "39920769daf78fce29a10c7f4e4bb8779671b004",
  contextDigest: "sha256:36933053249f2159d2b768e3ff62c3e114a587a5fa650df9b262b4f7d9b28d3b",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
};

const expectedM0S5BVendoredFiles = {
  "contracts/observability/obs-bind-001-local-v1.json":
    "873f6336786727ed62add025332b5c53abc68acc65da3a5c9ea93c922960adb4",
  "contracts/schemas/observability-binding.schema.json":
    "0dccea5ef9c8897fa5c4d66d3e9c586cf63531943ee423e474d071dad76c4d85",
  "contracts/schemas/semantic-fixtures/observability-binding-external-delivery.invalid.json":
    "2e36bac87a2fd40c885d7af78abe54ffacf308a34e4630ab42ce531fa06058ca",
};

const expectedM0S6AContext = {
  curveRevision: "d97cc053a5d0eac7bc2aa9bebe263a245c95894f",
  approvedContractHead: "421eae65d89c65a87e2d548cbe7b1e5d4e6236b5",
  planeBaseRevision: "cb17734280260361cc3c8eccf44170a4bfbcb840",
  contextDigest: "sha256:fcde6b95800c6bf657afe0cdf10cc28e1ddbb44aa16257833ca84f43714eedde",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
  implementer: "Codex",
};

const expectedM0S6AFiles = {
  "contracts/observability/m0-s5-telemetry-v1.json": "8ba95e5e605188e829df03374114eb2ec0d2cbea0218f1d286198cbbb2d34d9b",
  "contracts/schemas/examples/temporal-orchestration.invalid.json":
    "c06680da3869ad4f7519e931b0c5132b95f28ea6f29d1c9372514b8253eb293d",
  "contracts/schemas/examples/test-strategy-matrix.invalid.json":
    "5187e0ba131d3f3b83472e60c2f09d8507395d2b88ec51f91cedd26c3c60ace1",
  "contracts/schemas/telemetry-manifest.schema.json":
    "b25c1d758fa995370a01996b811770bdbd335374bda7ea88a790359d4c126942",
  "contracts/schemas/temporal-orchestration.schema.json":
    "9e5d72eea70d542dad9d15f372f0b90f5e68a0654735c3a7d2cd900df8b7fb47",
  "contracts/schemas/test-strategy-matrix.schema.json":
    "64fb3ce685c0d05ea5c5821b36843a76552361f0ad482397aa5d3bdadc5e7d16",
  "contracts/temporal/m0-orchestration-v1.json": "278b0845e7bf04200903d4cc110931e88b272df9ffb8da91eebf1984109a1374",
  "contracts/temporal/m0-workflow-contract.md": "8322debe600ff7f6f50e1e9da775879a353a1317b9b803ac4f65b413f1a7790e",
  "contracts/testing/ac-test-matrix-v1.json": "bad1a5a710ca16b3de399e1b0ff4b265d0c8ce64c203521f20e0d3f5ab2d3e3a",
  "docs/curve-ai-native-sdlc-prd.md": "3c37f73a97c903c7e4dd626e13e90be879bac1edd5de518660a63c0e9d6cfc6d",
  "docs/technical/adr-003-runtime-topology.md": "1f178fdea1afc68f4a2dab723ad936d54ec44869f9d6bbc8775a87003a3f6df8",
  "docs/technical/architecture.md": "a44d9aeb1bb2d7a56fd4c1edd21487873b010725194d738c29108b10f7ac81c8",
  "docs/technical/development-plan.md": "aaee3a2e42307dcd993a25e01df3fede75c2c7a8e01b3a9f3dd6ddbc008b03b5",
  "docs/technical/m0-s3-implementation-evidence.md": "69a6fed33741b219c208d78183ccba7051e7a4a4cccdcdf01ea16d049c3dcddf",
  "docs/technical/m0-s5b-implementation-evidence.md":
    "a42627fbb05519e14da71b7ace307d9a72de7ddc35f040fac78f1cec2b20623a",
  "docs/technical/m0-s6a-durable-orchestration-task-packet.md":
    "bf541c73de7fa4943ee93f33b82ceb6ad1013e174b09216ef7e0714bee3e1e5e",
  "docs/technical/m0-test-strategy.md": "3251aa103ebad931267d57c1a9f1f2f460b0292aa191850ff5986ed69892b28c",
  "docs/technical/m0-traceability.md": "6ea414862e7759b6b49bd9f88e529532422c1bc210295bcbd39642f7c0e9c848",
  "docs/technical/security-and-operations.md": "5223c206225efb448007ffba0fb5a127062e62c3e6ed9b6496ce03dadb5fdbdb",
  "docs/technical/workflows-and-sequences.md": "aad006efde398beab2bdebc82d0ddce4875a715245bc0d808f09eb506bc7a506",
  "scripts/lib/context-pack.mjs": "2a33f07d6d5a5bc0708faaff82eeeb40d97080cc9972f673900ef45ab5f212e7",
  "scripts/lib/temporal-orchestration.mjs": "0db93f23c83a28f9415c9cc8bf227cf7c38c890511acab3b9c1b380cf233ec5d",
  "scripts/lib/test-strategy.mjs": "29758a66137708d5a2ee739d0f7b215d7a882ed4943c7a3b2183b53abff445c1",
  "scripts/tests/temporal-orchestration.test.mjs": "fdf89c405384494ed1902bce16ad3677b00961577a1358eaa5fefedc6fdd3741",
  "scripts/tests/test-strategy.test.mjs": "0c3092c801d5e99043b090a28428967a28506670cd7f57b81b0497963fc1ace3",
  "scripts/validate-contracts.mjs": "d6163b4b238be852bba900d94942640dea73e1ad41b3930b13225d3a7cb554eb",
};

const expectedM0S9AContext = {
  curveRevision: "e6e43ea7fdf99baf79922a4ae506bbcb73e7c4cb",
  approvedContractHead: "cf1ffb696b30f45e71a6edcaba062f67a3de7b8e",
  planeBaseRevision: "ad5772c0565c934e64ea90f892be1374819979be",
  contextDigest: "sha256:9e07550799a6e4d88a6734f9a98e0de59812402d983bc7291396332a6b214cb0",
  owner: "Federico Ocampo",
  reviewer: "Federico Ocampo",
  implementer: "Codex",
};

const expectedM0S9AVendoredFiles = {
  "contracts/policy/core-policy-v1.json": "e0c4a03e27fd2b53b0109856c1599804865469ebebfc480244f4e76f7653cc52",
  "contracts/policy/core-policy-v2.json": "2895b63392236afa07e6f0572d6ddb1c91aa7f40d37282f250019d2829ed5787",
  "contracts/providers/m0-s9a-provider-registry-v1.json":
    "393c33fa5343beb1fe05a445a015333334a27bf491d7850c64dcf0a7f265071a",
  "contracts/schemas/core-policy-manifest-v2.schema.json":
    "05e77c1f3db002cfc4d26c743d031c71661cf7106f8ac9c27b14a5aacaff38b9",
  "contracts/schemas/examples/core-policy-manifest-v2.invalid.json":
    "ac837ffb9a4372d5461453f7d1030bfd75c5628faab513f2b63e93ce1e51ca8f",
  "contracts/schemas/examples/core-policy-manifest-v2.valid.json":
    "1db369e879a099af7ce44822c639e489296ab632144f602c5ea0c4f734a482f3",
  "contracts/schemas/examples/provider-capability.invalid.json":
    "4ba9691457bd3f3c4b919e927de34d68929c9045c183dd89dbee174b54a5044f",
  "contracts/schemas/examples/provider-capability.valid.json":
    "e402f29c92697837f7a51d364dfd40a247fb9703c459cd30f110a98507e4a3fa",
  "contracts/schemas/examples/provider-connection-event-v1.invalid.json":
    "04957aafa9fd614254e1d60483a9ee0bde97cb7a6f8866c88908c48ec1deabc3",
  "contracts/schemas/examples/provider-connection-event-v1.valid.json":
    "ff4b883a4f455ad7977ebcb85ebfb0508b5a9d5f7594d60c95ab58e7e18cdc92",
  "contracts/schemas/examples/provider-connection.invalid.json":
    "223540eb8a89f59db0dc94d9501ab4094770563a0636dccaf99ab28956f5c2a6",
  "contracts/schemas/examples/provider-connection.valid.json":
    "10e5bc9ebb2260b268227e0c08ac5ab4a373c73cc38a8b98642b3b69039535f0",
  "contracts/schemas/examples/provider-reconciliation-event-v1.invalid.json":
    "f17f6ac6e19636f9c3235210adddcd7690c42d96f6c236847d94b73d6c11c4ef",
  "contracts/schemas/examples/provider-reconciliation-event-v1.valid.json":
    "a5f67491e5e73699ecf83509a3c212dc6f50999b5984207d5cf7000929e4f8f5",
  "contracts/schemas/examples/provider-registry-manifest.invalid.json":
    "a1736ce37a59336442aea2f104f4c7b703a2e0b8331c01aa5eae196f3eaab2b6",
  "contracts/schemas/examples/provider-registry-manifest.valid.json":
    "e212248879c99b71cb24e91318e9eae4a30080e5a81d7013049135f0fadb0b2a",
  "contracts/schemas/policy-decision.schema.json": "6463d429124ee71df9ee57885dd332b703f86e35bbf65db161c3327723650799",
  "contracts/schemas/provider-capability.schema.json":
    "30d1388ed0367c194d05c88247d18563d2e2813bb80bdbe9a19605d8fd1228e7",
  "contracts/schemas/provider-connection-event-v1.schema.json":
    "8270ac5bb8cfb7474bbb3fb31f91be3787412dcea0dc58e1bf9ed427c3a99d43",
  "contracts/schemas/provider-connection.schema.json":
    "8485a48282cfe14f95bd4a3e64eb5de4353f6b6d22fab73c985c4763e1a5cdde",
  "contracts/schemas/provider-reconciliation-event-v1.schema.json":
    "d2b32ffba961eba6faa4b17d2aa718ac8c98c1ea67ec53cc4cacf54436569147",
  "contracts/schemas/provider-registry-manifest.schema.json":
    "df09e3a13953ce37ebd2555ecc53bdd133baf172d575a9ae95609ffcba4b3729",
  "contracts/schemas/semantic-fixtures/policy-decision-provider-registration-v2.valid.json":
    "42071ddb1a92c8265221aaa27c8409486c615011016972edb27567a47751597a",
  "contracts/schemas/semantic-fixtures/policy-decision-provider-registration-v3.invalid.json":
    "d86efaa2748146665dcf898f841cb9200e2da82a55cebbc89cbccb3afb442be1",
  "contracts/schemas/semantic-fixtures/provider-connection-active-null.invalid.json":
    "9207c17586bcd8cef2449bfa98be94aab0b1f19b2b5cfd89807cad8eee4f5239",
  "contracts/schemas/semantic-fixtures/provider-connection-active.valid.json":
    "b139b2c2812bcda6804f6643503e3cd048914b6318480c3076639a85495255b9",
  "contracts/schemas/semantic-fixtures/provider-connection-event-registered.valid.json":
    "15f073f83937859ad632dfb4c31433cbb093f670ce023fb1f40f97a696a5035f",
  "contracts/schemas/semantic-fixtures/provider-connection-revoked-next.invalid.json":
    "9bb7a9cb7690c1a4f952a27c43ba332ae895da8a02a04c0738f1c59f242533b6",
};

const fail = (message) => {
  throw new Error(`Curve contract integrity check failed: ${message}`);
};

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
// Historical manifests keep their approved digest; the current M0-S9A section
// independently binds the evolved schema bytes.
const evolvedAfterHistoricalContexts = new Set(["contracts/schemas/policy-decision.schema.json"]);

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
    if (!evolvedAfterHistoricalContexts.has(sourcePath)) {
      const fileName = sourcePath.split("/").at(-1);
      const directory = sourcePath.includes("/policy/") ? policyDirectory : schemaDirectory;
      const observedDigest = sha256(await readFile(new URL(fileName, directory)));
      if (observedDigest !== expectedDigest) {
        fail(`${fileName} digest ${observedDigest} does not match ${expectedDigest}`);
      }
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
    if (!evolvedAfterHistoricalContexts.has(sourcePath)) {
      const fileName = sourcePath.split("/").at(-1);
      const directory = sourcePath.includes("/policy/") ? policyDirectory : schemaDirectory;
      const observedDigest = sha256(await readFile(new URL(fileName, directory)));
      if (observedDigest !== expectedDigest) {
        fail(`${fileName} digest ${observedDigest} does not match M0-S3 source ${expectedDigest}`);
      }
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

const m0s5Context = JSON.parse(await readFile(m0s5ContextPath, "utf8"));
if (m0s5Context.schema_version !== "curve-context-pack/v1" || m0s5Context.task_id !== "M0-08") {
  fail("unexpected M0-S5 context identity");
}
if (
  m0s5Context.curve_revision !== expectedM0S5Context.curveRevision ||
  m0s5Context.approved_contract_head !== expectedM0S5Context.approvedContractHead ||
  m0s5Context.plane_base_revision !== expectedM0S5Context.planeBaseRevision ||
  m0s5Context.context_digest !== expectedM0S5Context.contextDigest
) {
  fail("unexpected M0-S5 revision or context digest");
}
if (
  m0s5Context.human_owner !== expectedM0S5Context.owner ||
  m0s5Context.human_reviewer !== expectedM0S5Context.reviewer ||
  m0s5Context.data_classification !== "INTERNAL" ||
  m0s5Context.execution_scope !== "LOCAL_ONLY"
) {
  fail("unexpected M0-S5 ownership, classification, or execution scope");
}
if (
  m0s5Context.approval_evidence?.curve_pr !== "https://github.com/faocampo/curve/pull/19" ||
  m0s5Context.approval_evidence?.approved_head !== expectedM0S5Context.approvedContractHead ||
  m0s5Context.approval_evidence?.squash_commit !== expectedM0S5Context.curveRevision
) {
  fail("unexpected M0-S5 approval evidence");
}
if (!Array.isArray(m0s5Context.files) || !Array.isArray(m0s5Context.paths)) {
  fail("M0-S5 context paths and per-file digests are required");
}
if (JSON.stringify(m0s5Context.paths) !== JSON.stringify([...m0s5Context.paths].toSorted())) {
  fail("M0-S5 context paths are not sorted");
}
if (JSON.stringify(m0s5Context.files.map(({ path }) => path)) !== JSON.stringify(m0s5Context.paths)) {
  fail("M0-S5 context files and paths differ");
}
if (new Set(m0s5Context.paths).size !== m0s5Context.paths.length) {
  fail("M0-S5 context paths are not unique");
}
if (!m0s5Context.paths.includes("docs/technical/m0-s4-implementation-evidence.md")) {
  fail("M0-S5 context omits accepted M0-S4 implementation evidence");
}
for (const file of m0s5Context.files) {
  if (!/^sha256:[0-9a-f]{64}$/.test(file.sha256)) {
    fail(`M0-S5 context digest is invalid for ${file.path}`);
  }
}
const recordedM0S5Digests = new Map(m0s5Context.files.map(({ path, sha256: digest }) => [path, digest]));
await Promise.all(
  Object.entries(expectedM0S5VendoredFiles).map(async ([sourcePath, expectedDigest]) => {
    const fileName = sourcePath.split("/").at(-1);
    const directory = sourcePath.includes("/observability/") ? observabilityDirectory : schemaDirectory;
    const observedDigest = sha256(await readFile(new URL(fileName, directory)));
    if (observedDigest !== expectedDigest) {
      fail(`${sourcePath} digest ${observedDigest} does not match M0-S5 source ${expectedDigest}`);
    }
    if (recordedM0S5Digests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-S5 context manifest`);
    }
  })
);

console.log(
  `Curve M0-S5 context integrity passed: ${m0s5Context.paths.length} files at ${expectedM0S5Context.curveRevision}`
);

const m0s5bContext = JSON.parse(await readFile(m0s5bContextPath, "utf8"));
if (m0s5bContext.schema_version !== "curve-context-pack/v1" || m0s5bContext.task_id !== "M0-S5B") {
  fail("unexpected M0-S5B context identity");
}
if (
  m0s5bContext.curve_revision !== expectedM0S5BContext.curveRevision ||
  m0s5bContext.approved_contract_head !== expectedM0S5BContext.approvedContractHead ||
  m0s5bContext.plane_base_revision !== expectedM0S5BContext.planeBaseRevision ||
  m0s5bContext.context_digest !== expectedM0S5BContext.contextDigest
) {
  fail("unexpected M0-S5B revision or context digest");
}
if (
  m0s5bContext.human_owner !== expectedM0S5BContext.owner ||
  m0s5bContext.human_reviewer !== expectedM0S5BContext.reviewer ||
  m0s5bContext.data_classification !== "INTERNAL" ||
  m0s5bContext.execution_scope !== "LOCAL_ONLY"
) {
  fail("unexpected M0-S5B ownership, classification, or execution scope");
}
if (
  m0s5bContext.approval_evidence?.curve_pr !== "https://github.com/faocampo/curve/pull/24" ||
  m0s5bContext.approval_evidence?.approved_head !== expectedM0S5BContext.approvedContractHead ||
  m0s5bContext.approval_evidence?.squash_commit !== expectedM0S5BContext.curveRevision
) {
  fail("unexpected M0-S5B approval evidence");
}
if (!Array.isArray(m0s5bContext.files) || !Array.isArray(m0s5bContext.paths)) {
  fail("M0-S5B context paths and per-file digests are required");
}
if (JSON.stringify(m0s5bContext.paths) !== JSON.stringify([...m0s5bContext.paths].toSorted())) {
  fail("M0-S5B context paths are not sorted");
}
if (JSON.stringify(m0s5bContext.files.map(({ path }) => path)) !== JSON.stringify(m0s5bContext.paths)) {
  fail("M0-S5B context files and paths differ");
}
if (new Set(m0s5bContext.paths).size !== m0s5bContext.paths.length) {
  fail("M0-S5B context paths are not unique");
}
for (const requiredPath of [
  "contracts/observability/obs-bind-001-local-v1.json",
  "contracts/schemas/observability-binding.schema.json",
  "contracts/schemas/semantic-fixtures/observability-binding-external-delivery.invalid.json",
  "docs/technical/m0-s5a-implementation-evidence.md",
  "docs/technical/obs-bind-001-local-observability-binding.md",
]) {
  if (!m0s5bContext.paths.includes(requiredPath)) {
    fail(`M0-S5B context omits ${requiredPath}`);
  }
}
for (const file of m0s5bContext.files) {
  if (!/^sha256:[0-9a-f]{64}$/.test(file.sha256)) {
    fail(`M0-S5B context digest is invalid for ${file.path}`);
  }
}
const recordedM0S5BDigests = new Map(m0s5bContext.files.map(({ path, sha256: digest }) => [path, digest]));
await Promise.all(
  Object.entries(expectedM0S5BVendoredFiles).map(async ([sourcePath, expectedDigest]) => {
    const fileName = sourcePath.split("/").at(-1);
    const directory = sourcePath.includes("/observability/")
      ? observabilityDirectory
      : sourcePath.includes("/semantic-fixtures/")
        ? semanticFixtureDirectory
        : schemaDirectory;
    const observedDigest = sha256(await readFile(new URL(fileName, directory)));
    if (observedDigest !== expectedDigest) {
      fail(`${sourcePath} digest ${observedDigest} does not match M0-S5B source ${expectedDigest}`);
    }
    if (recordedM0S5BDigests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-S5B context manifest`);
    }
  })
);

console.log(
  `Curve M0-S5B context integrity passed: ${m0s5bContext.paths.length} files at ${expectedM0S5BContext.curveRevision}`
);

const m0s6aContext = JSON.parse(await readFile(m0s6aContextPath, "utf8"));
if (m0s6aContext.schema_version !== "curve-context-pack/v1" || m0s6aContext.task_id !== "M0-S6A") {
  fail("unexpected M0-S6A context identity");
}
if (
  m0s6aContext.curve_revision !== expectedM0S6AContext.curveRevision ||
  m0s6aContext.approved_contract_head !== expectedM0S6AContext.approvedContractHead ||
  m0s6aContext.plane_base_revision !== expectedM0S6AContext.planeBaseRevision ||
  m0s6aContext.context_digest !== expectedM0S6AContext.contextDigest
) {
  fail("unexpected M0-S6A revision or context digest");
}
if (
  m0s6aContext.human_owner !== expectedM0S6AContext.owner ||
  m0s6aContext.human_reviewer !== expectedM0S6AContext.reviewer ||
  m0s6aContext.implementer !== expectedM0S6AContext.implementer ||
  m0s6aContext.data_classification !== "INTERNAL" ||
  m0s6aContext.execution_scope !== "LOCAL_ONLY" ||
  m0s6aContext.budget_usd !== 25
) {
  fail("unexpected M0-S6A ownership, classification, execution scope, or budget");
}
if (
  m0s6aContext.approval_evidence?.curve_pr !== "https://github.com/faocampo/curve/pull/28" ||
  m0s6aContext.approval_evidence?.approved_head !== expectedM0S6AContext.approvedContractHead ||
  m0s6aContext.approval_evidence?.squash_commit !== expectedM0S6AContext.curveRevision ||
  m0s6aContext.dispatch?.branch !== "curve/m0-s6a-durable-orchestration" ||
  m0s6aContext.dispatch?.authorized_by !== "Federico Ocampo" ||
  m0s6aContext.dispatch?.runtime !== "LOCAL_ONLY" ||
  m0s6aContext.dispatch?.merge_authorized !== false ||
  m0s6aContext.dispatch?.deployment_authorized !== false
) {
  fail("unexpected M0-S6A approval or dispatch evidence");
}
if (!Array.isArray(m0s6aContext.files) || !Array.isArray(m0s6aContext.paths)) {
  fail("M0-S6A context paths and per-file digests are required");
}
if (JSON.stringify(m0s6aContext.paths) !== JSON.stringify([...m0s6aContext.paths].toSorted())) {
  fail("M0-S6A context paths are not sorted");
}
if (JSON.stringify(m0s6aContext.files.map(({ path }) => path)) !== JSON.stringify(m0s6aContext.paths)) {
  fail("M0-S6A context files and paths differ");
}
if (
  new Set(m0s6aContext.paths).size !== m0s6aContext.paths.length ||
  m0s6aContext.paths.length !== Object.keys(expectedM0S6AFiles).length
) {
  fail("M0-S6A context path set is not exact and unique");
}
const recordedM0S6ADigests = new Map(m0s6aContext.files.map(({ path, sha256: digest }) => [path, digest]));
for (const [sourcePath, expectedDigest] of Object.entries(expectedM0S6AFiles)) {
  if (recordedM0S6ADigests.get(sourcePath) !== `sha256:${expectedDigest}`) {
    fail(`${sourcePath} is not byte-bound by the M0-S6A context manifest`);
  }
}
const expectedM0S6AVendoredFiles = new Map([
  ["contracts/schemas/temporal-orchestration.schema.json", schemaDirectory],
  ["contracts/temporal/m0-orchestration-v1.json", temporalDirectory],
]);
await Promise.all(
  Array.from(expectedM0S6AVendoredFiles, async ([sourcePath, directory]) => {
    const fileName = sourcePath.split("/").at(-1);
    const observedDigest = sha256(await readFile(new URL(fileName, directory)));
    if (observedDigest !== expectedM0S6AFiles[sourcePath]) {
      fail(`${sourcePath} vendored bytes differ from the approved M0-S6A source`);
    }
  })
);

const orchestrationManifest = JSON.parse(
  await readFile(new URL("m0-orchestration-v1.json", temporalDirectory), "utf8")
);
if (
  orchestrationManifest.schema_version !== "curve.temporal-orchestration/v1" ||
  orchestrationManifest.authority?.environment !== "LOCAL_ONLY" ||
  orchestrationManifest.authority?.temporal_python_sdk !== "1.31.0" ||
  orchestrationManifest.authority?.external_side_effects_allowed !== false ||
  orchestrationManifest.scheduling?.provider_dispatch_allowed !== false
) {
  fail("M0-S6A orchestration authority is broadened");
}
const expectedWorkflowNames = ["CurveInitiativeOrchestrationWorkflowV1", "CurveSliceAttemptWorkflowV1"];
if (
  JSON.stringify(orchestrationManifest.workflow_types?.map(({ name }) => name)) !==
  JSON.stringify(expectedWorkflowNames)
) {
  fail("M0-S6A workflow type set differs from the approved contract");
}
const handlerFields = [
  ...(orchestrationManifest.workflow_types ?? []).flatMap(({ input_fields, state_fields, output_fields }) =>
    input_fields.concat(state_fields, output_fields)
  ),
  ...(orchestrationManifest.signals ?? []).flatMap(({ fields }) => fields),
  ...(orchestrationManifest.queries ?? []).flatMap(({ fields }) => fields),
];
for (const fragment of orchestrationManifest.payload_policy?.forbidden_field_fragments ?? []) {
  if (handlerFields.some((field) => field.includes(fragment))) {
    fail(`M0-S6A handler field contains forbidden fragment ${fragment}`);
  }
}
if (
  JSON.stringify(orchestrationManifest.acceptance_tests) !==
  JSON.stringify(Array.from({ length: 12 }, (_, index) => `M0-S6A-AT-${String(index + 1).padStart(2, "0")}`))
) {
  fail("M0-S6A acceptance-test set is incomplete or unordered");
}

console.log(
  `Curve M0-S6A context integrity passed: ${m0s6aContext.paths.length} files at ${expectedM0S6AContext.curveRevision}`
);

const m0s9aContext = JSON.parse(await readFile(m0s9aContextPath, "utf8"));
if (m0s9aContext.schema_version !== "curve-context-pack/v1" || m0s9aContext.task_id !== "M0-S9A") {
  fail("unexpected M0-S9A context identity");
}
if (
  m0s9aContext.curve_revision !== expectedM0S9AContext.curveRevision ||
  m0s9aContext.approved_contract_head !== expectedM0S9AContext.approvedContractHead ||
  m0s9aContext.plane_base_revision !== expectedM0S9AContext.planeBaseRevision ||
  m0s9aContext.context_digest !== expectedM0S9AContext.contextDigest
) {
  fail("unexpected M0-S9A revision or context digest");
}
if (
  m0s9aContext.human_owner !== expectedM0S9AContext.owner ||
  m0s9aContext.human_reviewer !== expectedM0S9AContext.reviewer ||
  m0s9aContext.implementer !== expectedM0S9AContext.implementer ||
  m0s9aContext.data_classification !== "INTERNAL" ||
  m0s9aContext.execution_scope !== "LOCAL_ONLY" ||
  m0s9aContext.budget_usd !== 25
) {
  fail("unexpected M0-S9A ownership, classification, execution scope, or budget");
}
if (
  m0s9aContext.approval_evidence?.curve_pr !== "https://github.com/faocampo/curve/pull/37" ||
  m0s9aContext.approval_evidence?.approved_head !== expectedM0S9AContext.approvedContractHead ||
  m0s9aContext.approval_evidence?.squash_commit !== expectedM0S9AContext.curveRevision ||
  m0s9aContext.approval_evidence?.ci !== "https://github.com/faocampo/curve/actions/runs/33197154638" ||
  m0s9aContext.dispatch?.branch !== "curve/m0-s9a-provider-registry-foundation" ||
  m0s9aContext.dispatch?.authorized_by !== "Federico Ocampo" ||
  m0s9aContext.dispatch?.runtime !== "LOCAL_ONLY" ||
  m0s9aContext.dispatch?.merge_authorized !== false ||
  m0s9aContext.dispatch?.deployment_authorized !== false
) {
  fail("unexpected M0-S9A approval or dispatch evidence");
}
if (!Array.isArray(m0s9aContext.files) || !Array.isArray(m0s9aContext.paths)) {
  fail("M0-S9A context paths and per-file digests are required");
}
if (JSON.stringify(m0s9aContext.paths) !== JSON.stringify([...m0s9aContext.paths].toSorted())) {
  fail("M0-S9A context paths are not sorted");
}
if (JSON.stringify(m0s9aContext.files.map(({ path }) => path)) !== JSON.stringify(m0s9aContext.paths)) {
  fail("M0-S9A context files and paths differ");
}
if (new Set(m0s9aContext.paths).size !== m0s9aContext.paths.length) {
  fail("M0-S9A context paths are not unique");
}
for (const file of m0s9aContext.files) {
  if (!/^sha256:[0-9a-f]{64}$/.test(file.sha256)) {
    fail(`M0-S9A context digest is invalid for ${file.path}`);
  }
}

const recordedM0S9ADigests = new Map(m0s9aContext.files.map(({ path, sha256: digest }) => [path, digest]));
const m0s9aDirectoryFor = (sourcePath) => {
  if (sourcePath.includes("/policy/")) return policyDirectory;
  if (sourcePath.includes("/providers/")) return providerDirectory;
  if (sourcePath.includes("/examples/")) return schemaExampleDirectory;
  if (sourcePath.includes("/semantic-fixtures/")) return semanticFixtureDirectory;
  return schemaDirectory;
};
await Promise.all(
  Object.entries(expectedM0S9AVendoredFiles).map(async ([sourcePath, expectedDigest]) => {
    if (recordedM0S9ADigests.get(sourcePath) !== `sha256:${expectedDigest}`) {
      fail(`${sourcePath} is not byte-bound by the M0-S9A context manifest`);
    }
    const fileName = sourcePath.split("/").at(-1);
    const observedDigest = sha256(await readFile(new URL(fileName, m0s9aDirectoryFor(sourcePath))));
    if (observedDigest !== expectedDigest) {
      fail(`${sourcePath} vendored bytes differ from the approved M0-S9A source`);
    }
  })
);

const providerRegistryManifest = JSON.parse(
  await readFile(new URL("m0-s9a-provider-registry-v1.json", providerDirectory), "utf8")
);
if (
  providerRegistryManifest.schema_version !== "curve.provider-registry/v1" ||
  providerRegistryManifest.package !== "M0-S9A" ||
  providerRegistryManifest.authority?.environment !== "LOCAL" ||
  providerRegistryManifest.authority?.external_network !== "DISABLED" ||
  providerRegistryManifest.authority?.credential_access !== "DISABLED" ||
  providerRegistryManifest.authority?.temporal_workflow !== "DISABLED" ||
  providerRegistryManifest.authority?.celery_task !== "DISABLED" ||
  providerRegistryManifest.authority?.background_loop !== "DISABLED" ||
  providerRegistryManifest.authority?.external_mutation !== "DISABLED"
) {
  fail("M0-S9A provider authority is broadened");
}
if (
  providerRegistryManifest.registration_authorization?.policy_version !== 2 ||
  providerRegistryManifest.registration_authorization?.trusted_role !== "PLATFORM_ADMINISTRATOR" ||
  providerRegistryManifest.registration_authorization?.plane_role !== 20 ||
  providerRegistryManifest.registration_authorization?.caller_supplied_role !== "REJECT" ||
  providerRegistryManifest.registration_authorization?.target_allowlist !== "REQUIRED" ||
  providerRegistryManifest.delivery?.destination !== "CURVE_PROVIDER_LOCAL_V1" ||
  providerRegistryManifest.delivery?.consumer_id !== "curve-provider-local-v1" ||
  providerRegistryManifest.delivery?.maximum_attempts !== 3 ||
  providerRegistryManifest.delivery?.exhausted_state !== "DEAD_LETTER" ||
  providerRegistryManifest.delivery?.next_command_drain_order !== "AFTER_ALLOW_RECEIPT_BEFORE_COMMAND_MUTATION" ||
  providerRegistryManifest.delivery?.denied_command_delivery_mutation !== "NONE" ||
  providerRegistryManifest.delivery?.expired_claim_at_maximum_attempts !== "DEAD_LETTER" ||
  providerRegistryManifest.reconciliation?.same_command_replay !== "RETURN_TERMINAL_OR_RESUME_PENDING" ||
  providerRegistryManifest.reconciliation?.pending_command_replay !== "RESUME_FROM_DURABLE_PHASE" ||
  providerRegistryManifest.reconciliation?.stale_result_error_code !== "OPTIMISTIC_CONCURRENCY" ||
  providerRegistryManifest.persistence?.workspace_reference_guard !== "INSTANCE_AND_QUERYSET" ||
  providerRegistryManifest.persistence?.bulk_workspace_reference_mutation !== "PROHIBITED" ||
  providerRegistryManifest.event_payload_contracts?.length !== 2
) {
  fail("M0-S9A authorization or local-delivery contract differs from approval");
}

console.log(
  `Curve M0-S9A context integrity passed: ${Object.keys(expectedM0S9AVendoredFiles).length} vendored files at ${expectedM0S9AContext.curveRevision}`
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
