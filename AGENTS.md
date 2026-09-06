# Agent Development Guide

## Repository delivery

Follow the approved [repository delivery policy](https://github.com/faocampo/curve/blob/77dbfe5f50e0ac3e585dd2b57e687fa425e780e2/docs/technical/repository-delivery-policy.md)
(PR scope, integration gates, evidence and safe remote-branch cleanup), approved
2026-09-06 for human-directed Curve/Plane development. Plane integrates into
`curve-integration` (the fork's default branch); verify the live base before starting.
The fork's `preview` tracks `makeplane/plane`'s `preview` exactly. Keep Curve changes
off that tracking branch. Bring upstream updates into `curve-integration` through
a reviewed and tested PR. Record exact tips, preserve divergent work and use an
exact-tip lease when synchronizing `preview`. Upstream synchronization has no
deployment authority; the fork's upstream push-triggered publishing workflow
remains disabled until separately authorized.

- Use one cohesive outcome per PR and reuse it for rework. Check existing and
  merged PRs for equivalent work before creating a branch or PR.
- Allow at most two open dependent PRs per workstream, including the root.
  Larger stacks require an explicit owner-approved, bounded exception.
- Resolve the oldest integration gate first. During human review, prioritize
  the reviewable flow or independent work; freeze additional dependent PRs.
- Finish validation, review, authorized merge, integration verification, handoff
  update and remote-branch retirement. Preserve exact-head evidence and approvals.
- Routine delivery and verified remote cleanup within the user's authorized scope
  need no repeated confirmation. Human UX/security gates and repository protections
  remain binding; production deployment and activation require separate authority.
- Delete only verified merged/superseded remote tips without unique work, open
  dependents or active use. Preserve local worktrees, changes, stashes and history.

The existing Initiative-shell stack remains held for owner UX acceptance of
document handling, reviewer responsibilities and operational-flow simplification.
These development instructions leave Curve-dispatched runtime authority unchanged.

## Commands

- `pnpm dev` - Start all dev servers (web:3000, admin:3001)
- `pnpm build` - Build all packages and apps
- `pnpm check` - Run all checks (format, lint, types)
- `pnpm check:lint` - OxLint across all packages
- `pnpm check:types` - TypeScript type checking
- `pnpm fix` - Auto-fix format and lint issues
- `pnpm turbo run <command> --filter=<package>` - Target specific package/app
- `pnpm --filter=@plane/ui storybook` - Start Storybook on port 6006

## Code Style

- **Imports**: Use `workspace:*` for internal packages, `catalog:` for external deps
- **TypeScript**: Strict mode enabled, all files must be typed
- **Formatting**: oxfmt, run `pnpm fix:format`
- **Linting**: OxLint with shared `.oxlintrc.json` config
- **Naming**: camelCase for variables/functions, PascalCase for components/types
- **Error Handling**: Use try-catch with proper error types, log errors appropriately
- **State Management**: MobX stores in `packages/shared-state`, reactive patterns
- **Testing**: All features require unit tests, use existing test framework per package
- **Components**: Build in `@plane/ui` with Storybook for isolated development

## Document References

- Every reference to a document, specification, ADR, requirement set, task packet, or file must immediately include a brief title or content summary in parentheses. Apply this convention in agent updates, plans, reviews, implementation notes, PR descriptions, and generated documentation. Examples: `D-003 (runtime topology and trust-zone decision)` and `development-plan.md (milestones, dependencies, and delivery sequencing)`.

## Backend tests (Docker)

The Django/pytest suite for `apps/api` runs in an isolated stack defined by `docker-compose-test.yml` at the repo root.

Prereq (once): `./setup.sh` — generates `apps/api/.env` from `.env.example`.

- Full suite: `docker compose -f docker-compose-test.yml up --build --abort-on-container-exit --exit-code-from api-tests`
- Subset: `docker compose -f docker-compose-test.yml run --rm api-tests pytest -m unit`
- Teardown: `docker compose -f docker-compose-test.yml down -v`

See `apps/api/tests/RUNNING_TESTS.md` for the full walkthrough and troubleshooting; see `apps/api/tests/TESTING_GUIDE.md` for test conventions and fixtures.
