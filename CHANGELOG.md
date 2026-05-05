# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Chat **`[Current Time]`** and proactive context clocks honor **`local_timezone`** (IANA) instead of showing raw UTC when the server runs in UTC (e.g. Docker). When unset, they use the host OS local timezone.

### Added

- **Proactive messaging modes**: `proactive_mode` (`off` | `smart` | `scheduled`) with `proactive_schedule_times`, `proactive_schedule_interval_minutes`, and `proactive_schedule_require_idle`. Legacy JSON without `proactive_mode` derives mode from `proactive_enabled`; `proactive_enabled` is still saved and synced from mode on load. Environment: `MIRAI_PROACTIVE_MODE`, `MIRAI_PROACTIVE_SCHEDULE_TIMES`, `MIRAI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES`, `MIRAI_PROACTIVE_SCHEDULE_REQUIRE_IDLE`.
- **`local_timezone`** in `config.json`: IANA zone for user-facing wall time (chat clock, proactive context, proactive quiet hours, proactive daily limit calendar). Legacy JSON key `proactive_quiet_hours_timezone` is still read on load; prefer **`MIRAI_LOCAL_TIMEZONE`** over `MIRAI_PROACTIVE_QUIET_HOURS_TIMEZONE` at runtime.
- Proactive messaging: `proactive_check_interval_jitter_ratio`, `proactive_unreplied_escalation_jitter_ratio`, and `proactive_check_in_probability` for less rigid scheduling; matching `MIRAI_PROACTIVE_*` environment variables.

## [0.2.0] - 2026-04-20

### Changed

- **Repository split**: this `mirai-agent` package is now the open-source single-user / LAN core. Multi-tenant, relay, billing, admin, and remote-pairing features moved to the closed-source `mirai-enterprise` package, which extends the core via the new `mirai.core.plugins` port system (`IdentityProvider`, `QuotaPolicy`, `BotPool`, `MemoryFactory`, `SessionScope`, `EdgeScope`, `AuditSink`, `BillingHook`, `RouteExtender`, `MiddlewareExtender`).
- The OSS HTTP API now boots with `single_user` defaults: requests resolve to the local identity (`_local`), there is no Bearer auth requirement, and there are no quotas, billing, or per-tenant scoping.
- CLI surface trimmed to `--server`, `--ui`, `--chat`, `--telegram`, `--line`, `--edge`, `--demo`, `--setup`, `--cleanup`, `--cleanup-memory`. The provisioning / migration / relay flags (`--admin`, `--tenant-create`, `--user-add`, `--user-token`, `--user-token-revoke`, `--user-set-scope`, `--rotate-user-keys`, `--migrate-tenancy`, `--db-upgrade`, `--db-current`, `--db-stamp`, `--memory-prune`, `--relay`) ship in the enterprise CLI.
- `mirai.core.connection` is now LAN-only (`mode="direct"`); relay profile bootstrap, persistence, and the `mode="relay"` connection variant moved to enterprise.
- `mirai.core.auth` now exposes only `MiraiLanCode` and helpers; `MiraiCredential` (signed Bearer tokens) and refresh-token flows moved to enterprise.
- LINE bridge (`mirai.line.handlers`, `mirai.line.bridge`) is now stateless single-user; `/link`, `/usage`, per-LINE-user token persistence, and per-user model overrides moved to enterprise.
- Removed dependency pins on `slowapi` and `alembic` (multi-tenant rate-limit + DB migrations live in enterprise). The optional `postgres` extra is no longer published from OSS.

### Internal

- New `mirai/core/plugins/` package with `Identity`, `LOCAL_IDENTITY`, `Protocol` ports, single-user defaults, a runtime registry, and `entry_points`-based plugin discovery (`mirai.plugins` group).

## [0.1.x]

### Changed

- Internal Python layout: split user config into `mirai.core.config` package, prompts into `mirai.core.prompts`, memory helpers (`constants`, `tool_replay`, `embedding_state`), CLI as `mirai.cli` package with `terminal_chat`, streaming/error helpers, and renamed `mirai/tools/bootstrap.py` (was `setup.py`) for tool registration. User-facing HTTP routes, CLI commands, and SDKs are unchanged.
- Restricted default browser CORS for the core API and Relay to localhost-style origins, with explicit env vars for widening access.
- Refactored the core HTTP server into the `mirai.core.api` package (`routes`, `state`, `chat`, `edge`, `timers`, `peers`, `schemas`) to reduce module-level global state and improve testability.
- Expanded CI-safe tests: chat streaming, credential validation, Relay bootstrap/auth, CLI environment selection, edge WebSocket handshake, health endpoint, and cross-SDK contract tests (Python/Go/TypeScript/Java schema shape verification).
- Clarified public API stability, deployment hardening, and package metadata for external users.
- Replaced deprecated LanceDB `table_names()` checks with `list_tables()`-first compatibility helpers in memory storage to remove deprecation warnings on current releases.
- Added `build` to the development extras and documented a local pre-release smoke check for maintainers.
- Added `mirai --cleanup-memory` to clear persisted memory without deleting saved config, prompts, profiles, or connection codes.

[0.2.0]: https://github.com/wenxijiao/Mirai/releases/tag/v0.2.0

## [0.1.0] - 2026-04-11

### Added

- Initial documented release baseline: local-first agent, CLI (`mirai`), FastAPI server, Reflex web UI, multi-language edge SDKs, HTTP API and docs.

[0.1.0]: https://github.com/wenxijiao/Mirai/releases/tag/v0.1.0
