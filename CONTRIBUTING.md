# Contributing

## Scope

This project is a self-hosted Gmail knowledge and MCP stack. Contributions should preserve the privacy and safety assumptions already documented in `AGENTS.md` and the docs under `docs/`.

## Development Workflow

1. Create a branch from `main`.
2. For net-new features or substantial behavior changes, add or update specs under `specs/<feature-name>/`.
3. Keep changes focused and avoid unrelated cleanup in the same PR.
4. Do not commit secrets, tokens, or local OAuth files.

## Local Setup

```bash
cp .env.example .env
make up
```

For host-side Python commands, recreate a local virtualenv if needed:

```bash
python3 -m venv .venv
.venv/bin/pip install -r second-brain-service/requirements.txt
```

## Validation

Use the smallest meaningful validation for the change:

- `python -m compileall second-brain-service/src`
- `docker compose config`
- `make up`
- `curl http://localhost:8080/healthz`

If you change Python code and no narrower test exists, run:

```bash
python -m py_compile <touched_python_files>
```

## Pull Requests

- Explain the problem and the chosen approach.
- Call out user-visible behavior changes.
- Mention what you validated and what you did not validate.
- Keep private data out of issue descriptions, examples, and screenshots.
