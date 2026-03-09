# Project Structure Reorganization Task List

## Phase 1: Spec And Target Layout

Exit criteria: the reorganization spec exists and the target package skeleton is present.

- Create `specs/project-structure-reorg/requirements.md`
- Create `specs/project-structure-reorg/design.md`
- Create `specs/project-structure-reorg/task-list.md`
- Create `second-brain-service/src/second_brain_service/` package directories and `__init__.py` files
- Add `pyproject.toml`

## Phase 2: Code Boundary Refactor

Dependencies: Phase 1
Exit criteria: the service runs from `python -m second_brain_service.cli` with the same external behavior.

- Move config and sanitization helpers into `common/`
- Move Gmail sync into `ingest/`
- Move embeddings and retrieval boundary into `search/`
- Split database responsibilities across `store/connection.py`, `store/mail_repository.py`, and `store/maintenance.py`
- Extract HTTP API handling into `interfaces/http_api.py`
- Extract stdio MCP transport into `interfaces/stdio_mcp.py`
- Keep remote MCP and auth under `interfaces/`
- Remove the temporary `mcp_server` shim after all repo-managed references have moved

## Phase 3: Reference And Workspace Cleanup

Dependencies: Phase 2
Exit criteria: repo references point at `second-brain-service/` and root runtime artifacts are organized.

- Update `Makefile`, `docker-compose.yml`, and `Dockerfile` usage
- Update `README.md`, docs, and existing specs
- Move root `.tmp_*` artifacts under `tmp/`
- Remove obvious generated workspace clutter such as `.DS_Store` and Python caches
- Remove the `mcp_server` compatibility surface from the repo

## Phase 4: Verification

Dependencies: Phase 3
Exit criteria: targeted validation completes and any residual risks are documented.

- Run `python -m py_compile` for touched Python files
- Verify `python -m second_brain_service.cli --help`
- Verify `docker compose config`
- Run targeted local startup and API smoke checks where the environment allows
- Search for stale `mcp_server` references and confirm only intentional ones remain
