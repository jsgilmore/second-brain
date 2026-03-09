# Project Structure Reorganization Design

## Design Summary

This change reorganizes the workspace around a truthfully named Python service directory, `second-brain-service/`, with a package layout rooted at `src/second_brain_service/`. The refactor keeps external behavior stable while moving code out of the legacy flat module structure into responsibility-based modules.

## How The Design Satisfies The Requirements

- The top-level service name reflects the actual product scope rather than only one interface.
- A package layout under `src/` makes import boundaries explicit and packaging standard.
- Interface entrypoints are separated from ingest, search, and store logic.
- Connection helpers and maintenance tasks stop sharing a single module with repository queries.
- Root runtime and temp artifacts are grouped into the intended top-level directories.

## Target Structure

```text
second-brain-service/
  Dockerfile
  pyproject.toml
  requirements.txt
  src/second_brain_service/
    __init__.py
    cli.py
    common/
      __init__.py
      config.py
      sanitize.py
    interfaces/
      __init__.py
      http_api.py
      remote_auth.py
      remote_mcp.py
      stdio_mcp.py
    ingest/
      __init__.py
      gmail_sync.py
    search/
      __init__.py
      embeddings.py
      retrieval.py
    store/
      __init__.py
      connection.py
      mail_repository.py
      maintenance.py
```

## Move Manifest

- `mcp_server/Dockerfile` -> `second-brain-service/Dockerfile`
- `mcp_server/requirements.txt` -> `second-brain-service/requirements.txt`
- `mcp_server/src/config.py` -> `second-brain-service/src/second_brain_service/common/config.py`
- `mcp_server/src/sanitize.py` -> `second-brain-service/src/second_brain_service/common/sanitize.py`
- `mcp_server/src/embeddings.py` -> `second-brain-service/src/second_brain_service/search/embeddings.py`
- `mcp_server/src/gmail_sync.py` -> `second-brain-service/src/second_brain_service/ingest/gmail_sync.py`
- `mcp_server/src/remote_auth.py` -> `second-brain-service/src/second_brain_service/interfaces/remote_auth.py`
- `mcp_server/src/remote_mcp.py` -> `second-brain-service/src/second_brain_service/interfaces/remote_mcp.py`
- `mcp_server/src/db.py` -> `second-brain-service/src/second_brain_service/store/mail_repository.py`
- `mcp_server/src/app.py` -> logic redistributed into `cli.py`, `interfaces/http_api.py`, and `interfaces/stdio_mcp.py`
- `.tmp_compare.tsv` -> `tmp/root-artifacts/compare.tsv`
- `.tmp_quality.tsv` -> `tmp/root-artifacts/quality.tsv`
- `.tmp_raw_message.json` -> `tmp/root-artifacts/raw_message.json`

## Key Tradeoffs And Alternatives

- Chosen: phased compatibility during the migration, followed by shim removal once all repo-managed references moved.
  The temporary shim reduced change risk during the rename, but it is not part of the final steady state.
- Not chosen: preserving the shim indefinitely.
  That would keep transition risk low, but it would also leave the repo with a misleading duplicate entrypoint.
- Chosen: keep Docker Compose service names `mcp` and `mcp_remote`.
  That avoids unnecessary changes to container aliases and n8n references.

## Interfaces, Workflow, And Data Model Impact

- New canonical Python entrypoint: `python -m second_brain_service.cli`
- Docker commands use module execution instead of `python src/app.py`
- Make targets use the installed package entrypoint instead of the legacy path
- No changes to HTTP endpoint shapes, MCP tool names, DB schema, or Gmail credential paths

## Risks

- Import-path mistakes during the split can break startup for one or more entrypoints.
- The workspace is not under Git, so file moves are harder to audit after the fact.
- A leftover local script outside the repo may still reference `mcp_server/src/app.py`.
- Runtime smoke checks may depend on local Docker state and secrets that are outside source control.

## Rollout Plan

1. Create the structure-reorg spec docs and move manifest.
2. Introduce the package layout and move code behind package imports.
3. Update Dockerfile, Compose, Makefile, docs, and existing specs to the new service path.
4. Remove the temporary shim once Docker, Make, docs, and runtime references are fully migrated.
5. Clean workspace artifacts that are clearly non-source and non-essential to active runtime usage.

## Validation Plan

- Compile all touched Python modules with `py_compile`.
- Verify package import and CLI help from the new module path.
- Verify CLI help from the canonical `second_brain_service.cli` module path.
- Validate `docker compose config`.
- Run targeted runtime checks: startup, `/healthz`, `/search`, and remote MCP startup.
- Search the repo for stale `mcp_server` references and reduce them to historical documentation only.

## Open Questions

- None for this implementation pass. The scope is structural and compatibility-first.
