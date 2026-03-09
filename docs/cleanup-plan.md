# Cleanup Plan

The planned structure cleanup has been applied.

## Current structure

- `second-brain-service/` is the primary Python service directory.
- `second-brain-service/src/second_brain_service/` is the canonical package root.
- `config/`, `docs/`, `docker/`, `logs/`, `specs/`, and `tmp/` remain the intended top-level workspace categories.
- root temporary analysis files now live under `tmp/root-artifacts/`.

## Compatibility notes

- Docker Compose service keys remain `mcp` and `mcp_remote`.
- HTTP endpoints, remote MCP tools, and Gmail credential paths are unchanged.

## Remaining optional cleanup

- Remove backup virtualenvs if they are confirmed unused.
- Trim or rotate local logs as needed.
