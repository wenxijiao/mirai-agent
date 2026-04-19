# Testing

## How to run

```bash
python -m pip install -e ".[dev]"
pytest
```

Run a single file or match a test name:

```bash
pytest tests/test_stream_event.py
pytest tests/ -k stream_event
```

## Configuration

Pytest options live under `[tool.pytest.ini_options]` in the repo root [pyproject.toml](../pyproject.toml) (`testpaths = ["tests"]`).

## What CI runs

- **`pytest`** over the whole `tests/` tree.
- **`ruff check mirai tests`** — see [.github/workflows/ci.yml](../.github/workflows/ci.yml).

Optionally install [pre-commit](https://pre-commit.com/) locally; same hooks as described in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Current scope (kept lightweight on purpose)

By default, tests **do not** start the full `mirai --server` / FastAPI lifespan (avoids pulling models and binding ports in CI). Coverage today roughly includes:

| Area | What is checked |
|------|-----------------|
| HTTP stream shape | NDJSON lines from `stream_event`, plus `/chat` response streaming with a mocked generator |
| Config | `ModelConfig` defaults and CORS env parsing helpers |
| API models | Pydantic models in `mirai.core.api.schemas` |
| App object | `create_app()` returns the same instance as the module-level `app` (no listening socket) |
| Credentials | Encode/decode round-trip plus expiry / kind / scope / signature failures in `mirai.core.auth` |
| Relay auth | Bearer enforcement, scope rejection, and one-time join-code bootstrap behavior |
| CLI env | Direct-mode environment selection without launching subprocesses |
| Edge WebSocket | Register handshake, tool mounting, and disconnect cleanup via TestClient WebSocket |
| Health endpoint | `/health` response shape and default relay status |
| SDK contracts | Wire-format verification across Python, Go, TypeScript, and Java schema builders; register/tool_call/tool_result message shapes |

For end-to-end or HTTP tests with mocks, add cases separately (e.g. `TestClient` with dependencies overridden).
