// Public contract byte integrity; this checker supplies no human authority.
import { createHash } from "node:crypto";
import { readFile, readdir, lstat } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

export const EXPECTED_MANIFEST_SHA256 = "cd6896294dd41a9e7faa71e49892fe527bd19d7154d02368960645b7bb853a94";
const excluded = new Set(["check-integrity.mjs", "public-consumer-edition-v1.json"]);
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const fail = (message) => {
  throw new Error(message);
};

async function inventory(directory, prefix = "") {
  const entries = await readdir(directory);
  const paths = await Promise.all(
    entries.map(async (name) => {
      const path = prefix + name;
      const url = new URL(name, directory);
      const info = await lstat(url);
      if (info.isSymbolicLink()) fail("Contract symlinks are prohibited");
      if (info.isDirectory()) return inventory(new URL(name + "/", directory), path + "/");
      if (!info.isFile()) fail("Unsupported contract entry");
      return excluded.has(path) ? [] : [path];
    })
  );
  return paths.flat().toSorted();
}

export async function validateConsumerSnapshot(directory = new URL(".", import.meta.url)) {
  const bytes = await readFile(new URL("public-consumer-edition-v1.json", directory));
  if (sha256(bytes) !== EXPECTED_MANIFEST_SHA256) fail("Public consumer manifest digest mismatch");
  const manifest = JSON.parse(bytes);
  if (
    manifest.schema_version !== "curve.public-consumer-edition/v1" ||
    manifest.edition_id !== "curve-plane-public-contracts-v1" ||
    manifest.status !== "PUBLIC_REFERENCE" ||
    manifest.execution_authority !== "NONE" ||
    manifest.legacy_approval_transfer !== "PROHIBITED" ||
    manifest.source.revision !== "00fb40dad746a4e4ec2aefe9bc0f629e1118d716"
  ) {
    fail("Public consumer identity or authority mismatch");
  }
  const paths = manifest.files.map((item) => item.path);
  if (new Set(paths).size !== paths.length || JSON.stringify(paths) !== JSON.stringify(await inventory(directory))) {
    fail("Public consumer file inventory mismatch");
  }
  for (const item of manifest.files) {
    if (
      !/^[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(item.path) ||
      item.path.split("/").includes("..") ||
      !/^[0-9a-f]{64}$/.test(item.sha256)
    )
      fail("Invalid public consumer file pin");
  }
  await Promise.all(
    manifest.files.map(async (item) => {
      if (sha256(await readFile(new URL(item.path, directory))) !== item.sha256)
        fail(`Contract digest mismatch: ${item.path}`);
    })
  );
  const contextPaths = paths.filter(
    (path) => path.endsWith("-context.json") || path === "temporal/m0-s6a-runtime-evidence.json"
  );
  await Promise.all(
    contextPaths.map(async (path) => {
      const record = JSON.parse(await readFile(new URL(path, directory)));
      if (
        record.schema_version !== "curve-public-reference/v1" ||
        record.status !== "PUBLIC_REFERENCE" ||
        record.execution_authority !== "NONE" ||
        record.legacy_approval_transfer !== "PROHIBITED" ||
        record.publication_edition !== manifest.edition_id ||
        record.approval_evidence ||
        record.dispatch
      ) {
        fail("Historical approval transfer is prohibited");
      }
    })
  );

  const temporalDirectory = new URL("temporal/", directory);
  const providerDirectory = new URL("providers/", directory);
  const governanceDirectory = new URL("governance/", directory);
  const policyDirectory = new URL("policy/", directory);
  const temporalSupplyChainPath = new URL("temporal-supply-chain.json", directory);
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
    fail("M0-S6A workflow type set differs from the published reference");
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
    fail("M0-S9A authorization or local-delivery contract differs from the published reference");
  }
  const productDecision = JSON.parse(
    await readFile(new URL("m1-00a-product-core-v1.json", governanceDirectory), "utf8")
  );
  if (
    productDecision.decision_id !== "M1-00A" ||
    productDecision.status !== "APPROVED" ||
    productDecision.semantics?.key?.mutable !== false ||
    productDecision.semantics?.ownership?.active_owner_count !== 1 ||
    JSON.stringify(productDecision.semantics?.lifecycle?.states) !== JSON.stringify(["ACTIVE", "ARCHIVED"]) ||
    productDecision.semantics?.retirement !== "REVERSIBLE_ARCHIVAL"
  ) {
    fail("M1-00A Product semantics differ from the published decision semantics");
  }
  const initiativePolicy = JSON.parse(await readFile(new URL("initiative-policy-v1.json", policyDirectory), "utf8"));
  if (
    initiativePolicy.policy_key !== "CURVE_INITIATIVE_POLICY" ||
    initiativePolicy.policy_version !== 1 ||
    initiativePolicy.default_effect !== "DENY" ||
    JSON.stringify(initiativePolicy.enabled_modes) !== JSON.stringify(["STANDALONE"]) ||
    initiativePolicy.workflow_version_id !== "82000000-0000-4000-8000-000000000001"
  ) {
    fail("M1-01A Initiative policy differs from the published reference");
  }
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

  return { files: paths.length, edition: manifest.edition_id, execution_authority: "NONE" };
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const result = await validateConsumerSnapshot();
  console.log(`Curve public consumer integrity passed: ${result.files} files; execution authority: NONE`);
}
