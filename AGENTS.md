# AGENTS.md

## Purpose

This repository uses a spec-first workflow for new feature development and a safety-first workflow for automation changes.

When a request is about a new feature or substantial behavior change, do not begin implementation immediately. First produce planning docs under `specs/` and wait for user review.

## Default feature workflow

For any request that matches the feature trigger rules below:

1. Create a new feature folder at `specs/<feature-name>/`.
2. Create these files inside that folder:
   - `requirements.md`
   - `design.md`
   - `task-list.md`
3. Write `requirements.md` first.
   - Include goals, non-goals, user stories or use cases, constraints, and acceptance criteria.
4. Write `design.md` second.
   - The design must satisfy the requirements.
   - Include the proposed approach, alternatives or tradeoffs, affected interfaces or data model changes, risks, rollout plan, validation plan, and open questions.
5. Write `task-list.md` third.
   - The task list must realize the design.
   - Organize it into implementation phases with clear exit criteria, dependencies, and verification steps where appropriate.
6. Ask the user to review the three docs and wait for feedback.
7. Revise the docs based on feedback before building.
8. Do not start implementation until the user explicitly confirms to proceed.

## Feature trigger rules

Use the spec-first workflow when the request is any of the following:

- a net-new user-visible capability
- a substantial enhancement to existing behavior
- a behavior redesign with meaningful product impact
- a cross-module workflow or automation change
- a schema, API, ingestion, retrieval, or authentication change with product impact

If the request is borderline, ask one short clarifying question before skipping the spec-first workflow.

## Scope

Use the spec-first workflow when the request is clearly about:

- a new feature
- a substantial enhancement
- a new product capability
- a feature redesign that changes behavior significantly

## Exceptions

Do not require the spec-first workflow for:

- bug fixes
- small refactors
- documentation-only changes
- tests-only changes
- operational tasks
- one-off scripts
- small UI copy or styling tweaks

If the request is ambiguous, prefer asking a short clarifying question or making a reasonable judgment based on the size and risk of the change.

If the user explicitly says to skip specs and proceed directly, follow the user's instruction unless the change is unusually risky and clearly benefits from design review first.

## Spec conventions

- Keep specs under `specs/`, one folder per feature.
- Use short kebab-case feature folder names.
- Keep requirements, design, and task list as separate files.
- Prefer revising the existing feature spec folder over creating duplicates when work continues on the same feature.
- If a matching feature spec already exists, update it instead of creating a parallel folder unless the user asks for a separate track.
- Keep the initial spec docs concise and decision-oriented. Prefer focused sections over long prose dumps.

## Minimum spec contents

`requirements.md` must include:

- problem statement
- goals
- non-goals
- user stories or use cases
- constraints or assumptions
- acceptance criteria

`design.md` must include:

- design summary
- how the design satisfies the requirements
- key tradeoffs or alternatives considered
- interfaces, workflow, or data model impact
- risks
- rollout plan
- validation plan
- open questions

`task-list.md` must include:

- phased implementation steps
- dependencies or ordering constraints
- verification tasks
- exit criteria for major phases

If one of these sections is genuinely not needed, state that explicitly instead of omitting it silently.

## Open questions and decision hygiene

- Surface unresolved product, architecture, or scope decisions explicitly in the spec docs.
- Do not begin implementation while material open questions remain unresolved unless the user explicitly accepts those assumptions.
- When making an assumption to unblock a draft, label it clearly.

## Implementation gate

Implementation starts only after:

1. the user has reviewed the spec docs
2. material feedback has been incorporated or explicitly deferred
3. the user has explicitly confirmed that implementation should proceed

## Canonical commands

Prefer these existing entry points over ad hoc command sequences:

- `make up`
- `make down`
- `make ps`
- `make logs`
- `make apply-schema`
- `make rehydrate-gmail`
- `make gmail-backfill`
- `make gmail-backfill-resume`
- `make gmail-backfill-12mo`
- `make gmail-incremental`

Useful smoke checks:

- `curl http://localhost:8080/healthz`
- `curl http://localhost:8080/search -H 'Content-Type: application/json' -d '{"query":"test","limit":3}'`

If you change Python code and no better automated test exists, at minimum run:

- `./.venv/bin/python -m py_compile <touched_python_files>`

Prefer small, targeted verification over broad expensive runs unless the task justifies more.

## Automation safety rules

This repo handles private Gmail data, OAuth credentials, and automation surfaces. Treat changes as safety-sensitive by default.

Do not do any of the following without explicit user approval:

- expose a local-only service to the public internet
- relax authentication or authorization rules
- change allowed users or allowed domains for remote access
- rotate, replace, or overwrite OAuth credentials or tokens
- delete mailbox data, sync state, or checkpoints
- run destructive database commands
- send outbound mail or trigger external side effects on behalf of the user

For automation changes:

- prefer dry-run, validation, or no-op paths first when available
- make side effects explicit before executing them
- keep retry behavior bounded and visible
- preserve human approval points for sensitive actions

## Secrets and data handling

- Never commit secrets, tokens, or private credentials.
- Treat `.env`, OAuth client files, OAuth token files, and raw Gmail payloads as sensitive.
- Do not print API keys, OAuth tokens, session cookies, or authorization headers.
- Redact sensitive values in logs, examples, and screenshots.
- Avoid pasting full raw email bodies into docs unless the user explicitly wants that and the content is safe to persist.
- Minimize copying private mailbox content into new files.

When referring to local secret-bearing files, use paths and summaries rather than reproducing contents.

## Idempotency and recovery

Prefer implementations that are safe to retry.

For ingestion, sync, and background automation work:

- preserve or add checkpoints where practical
- make reruns deduplicate cleanly
- avoid designs that require manual cleanup after partial failure
- ensure long-running jobs can resume from saved state when possible
- prefer append-safe or upsert-based behavior over delete-and-rebuild flows unless explicitly required

If a task introduces a new long-running or scheduled process, document:

- how to start it
- how to verify it is healthy
- how to stop it
- how to recover from interruption

## Validation rules

Changes should be verified in proportion to risk.

For code changes:

- run the smallest meaningful validation that covers the change
- prefer existing Make targets and smoke checks
- report what was verified and what was not verified

For ingestion, schema, auth, or automation changes, prefer verifying all relevant layers:

- syntax or static validation
- service health
- targeted command or API smoke test
- data-path verification where applicable

If full end-to-end verification is not possible, say so explicitly and identify the remaining risk.

## Observability

Favor changes that make automation easier to inspect and recover.

Prefer:

- structured or at least consistent logs
- explicit progress reporting for long-running jobs
- clear error messages with enough context to debug
- stable artifact and file paths
- summaries of failures, skips, retries, and partial completion

Sanitize logs so they do not leak secrets or unnecessary mailbox content.

## Instruction hygiene

- Keep this top-level file concise and practical.
- Add more specific nested `AGENTS.md` files later for subtrees that need local rules.
- Avoid duplicating or conflicting instructions across files.
- Prefer concrete commands and repository-specific conventions over generic advice.
