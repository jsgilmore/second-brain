# Project Structure Reorganization Requirements

## Problem Statement

The workspace layout no longer matches the system boundaries it contains. The current `mcp_server/` directory is a legacy catch-all for Gmail ingestion, storage, retrieval, HTTP serving, stdio MCP, and remote MCP. The project root also contains runtime artifacts and temporary analysis files that make source boundaries less clear than they should be.

## Goals

- Rename the main Python service directory to `second-brain-service/`.
- Introduce a real Python package rooted at `src/second_brain_service/`.
- Separate service responsibilities into clearer modules for interfaces, ingest, search, and store.
- Keep existing HTTP, MCP, Gmail credential, and Make target behavior stable during the refactor.
- Clean obvious non-source artifacts out of the project root.
- Record the reorganization plan, move manifest, and migration phases in a durable spec.

## Non-Goals

- Redesign the product behavior, API surface, or authentication model.
- Replace Docker Compose service names.
- Introduce a database migration framework.
- Change Gmail sync semantics, search ranking behavior, or remote MCP tool contracts.

## Use Cases

- A maintainer should be able to identify where HTTP handlers live without reading the Gmail sync code.
- A maintainer should be able to update Gmail ingestion without touching remote MCP or CLI bootstrapping.
- A maintainer should be able to find database connection code, repository queries, and maintenance helpers in separate modules.
- A new contributor should be able to understand which root directories are source, configuration, documentation, logs, and temporary artifacts.

## Constraints And Assumptions

- Existing HTTP endpoints and MCP tool names must remain unchanged.
- Existing credential paths under `config/` must remain unchanged.
- Existing Make targets should continue to work after reference updates.
- The workspace is not currently a Git repository, so rename history cannot be used as the sole move record.
- Runtime-local directories such as `logs/`, `tmp/`, and `config/` remain root-level.

## Acceptance Criteria

- A new spec folder exists at `specs/project-structure-reorg/` with requirements, design, and task tracking.
- The main service code lives under `second-brain-service/src/second_brain_service/`.
- any temporary compatibility shim is removed once all repo-managed references have moved to `second-brain-service/`.
- The codebase contains dedicated modules for `interfaces/http_api.py`, `interfaces/stdio_mcp.py`, `interfaces/remote_mcp.py`, `interfaces/remote_auth.py`, `ingest/gmail_sync.py`, `search/embeddings.py`, `search/retrieval.py`, `store/connection.py`, `store/mail_repository.py`, and `store/maintenance.py`.
- Docker, Make, docs, and existing specs reference `second-brain-service/` instead of `mcp_server/`.
- Root-level `.tmp_*` files are moved under `tmp/`.
- Validation covers Python compilation, package import/CLI checks, Compose config resolution, and targeted runtime smoke checks.
