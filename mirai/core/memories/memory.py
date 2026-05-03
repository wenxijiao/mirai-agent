from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import lancedb
from mirai.core.config import load_model_config, migrate_legacy_memory_dir, save_model_config
from mirai.core.memories import transcript as _transcript
from mirai.core.memories.constants import (
    ACTIVE_SESSION_STATUS,
    DEFAULT_SESSION_TITLE,
    DELETED_SESSION_STATUS,
)
from mirai.core.memories.embedding_state import (
    get_embed_provider,
)
from mirai.core.memories.embedding_state import (
    is_degenerate_vector as _is_degenerate_vector,
)
from mirai.core.memories.models import (
    LONG_TERM_MEMORY_KINDS,
    LONG_TERM_TABLE,
    SESSION_SUMMARY_TABLE,
    TOOL_OBSERVATION_TABLE,
    decode_json_list,
    encode_json,
)
from mirai.core.memories.sessions import derive_session_title, normalize_session_status, normalize_session_title
from mirai.core.memories.storage import add_row, query_rows, replace_row
from mirai.core.memories.tool_replay import persist_openai_messages as _tool_replay_persist
from mirai.core.prompts.store import get_effective_system_prompt
from mirai.logging_config import get_logger

logger = get_logger(__name__)


def _assistant_tool_call_count_from_stored_raw(raw: str) -> int | None:
    return _transcript.assistant_tool_call_count_from_stored_raw(raw)


def _trim_trailing_incomplete_tool_rows(rows: list[dict]) -> list[dict]:
    return _transcript.trim_trailing_incomplete_tool_rows(rows)


def _trim_leading_orphan_tool_rows(rows: list[dict]) -> list[dict]:
    return _transcript.trim_leading_orphan_tool_rows(rows)


def _trim_leading_orphan_assistant_tool_calls(rows: list[dict]) -> list[dict]:
    return _transcript.trim_leading_orphan_assistant_tool_calls(rows)


def _dedupe_consecutive_user_rows(rows: list[dict]) -> list[dict]:
    return _transcript.dedupe_consecutive_user_rows(rows)


class Memory:
    _shared_db: dict[str, object] = {}
    _initialized_dirs: set[str] = set()
    _init_lock = threading.Lock()

    def __init__(self, session_id="default", system_prompt=None, storage_dir=None, max_recent=10):
        self.db_dir = storage_dir if storage_dir else str(migrate_legacy_memory_dir())

        self.session_id = session_id
        self.max_recent = max_recent
        # system_prompt is ignored here: callers must persist via mirai.core.prompts.set_session_prompt
        # (Memory no longer writes the prompt store on construction.)

        config = load_model_config()
        self.embed_model = config.embedding_model
        self._embed_provider = get_embed_provider()
        self._embedding_available = self._check_embedding_available()
        self._fallback_vector_size = 1024

        self.table_name = "chat_history"
        self.session_table_name = "chat_sessions"
        self.long_term_table_name = LONG_TERM_TABLE
        self.tool_observation_table_name = TOOL_OBSERVATION_TABLE
        self.session_summary_table_name = SESSION_SUMMARY_TABLE

        with Memory._init_lock:
            if self.db_dir not in Memory._shared_db:
                Memory._shared_db[self.db_dir] = lancedb.connect(self.db_dir)

        self.db = Memory._shared_db[self.db_dir]

        with Memory._init_lock:
            if self.db_dir not in Memory._initialized_dirs:
                Memory._initialized_dirs.add(self.db_dir)
                self._init_tables()
                self._check_embedding_dim_migration()

    def _init_tables(self):
        self._init_message_table()
        self._init_session_table()

    def _list_table_names(self, db=None) -> set[str]:
        target_db = db or self.db
        list_tables = getattr(target_db, "list_tables", None)
        if callable(list_tables):
            result = list_tables()
            names = getattr(result, "tables", result)
            return {str(name) for name in names}
        return {str(name) for name in target_db.table_names()}

    def _has_table(self, table_name: str, db=None) -> bool:
        return table_name in self._list_table_names(db)

    def _init_message_table(self):
        if not self._has_table(self.table_name):
            return

        table = self.db.open_table(self.table_name)
        schema_fields = set(table.schema.names)
        required_fields = {
            "id",
            "vector",
            "session_id",
            "role",
            "content",
            "timestamp",
            "timestamp_num",
        }

        if required_fields.issubset(schema_fields):
            self._ensure_thought_column()
            return

        self._migrate_message_table(table)
        self._ensure_thought_column()

    def _migrate_message_table(self, table):
        rows = table.to_pandas().to_dict(orient="records")
        migrated_rows = []
        fallback_timestamp_num = int(datetime.now(timezone.utc).timestamp() * 1000)

        for index, row in enumerate(rows):
            content = row.get("content", "") or ""
            vector = row.get("vector")
            timestamp = row.get("timestamp") or self._format_timestamp()
            timestamp_num = self._parse_timestamp_num(
                row.get("timestamp_num"),
                timestamp,
                fallback_timestamp_num + index,
            )

            migrated_rows.append(
                {
                    "id": row.get("id") or str(uuid.uuid4()),
                    "vector": self._normalize_vector(vector, content),
                    "session_id": row.get("session_id") or self.session_id,
                    "role": row.get("role") or "user",
                    "content": content,
                    "timestamp": timestamp,
                    "timestamp_num": timestamp_num,
                    "thought": str(row.get("thought") or ""),
                }
            )

        self.db.drop_table(self.table_name, ignore_missing=True)
        if migrated_rows:
            self.db.create_table(self.table_name, data=migrated_rows)

    def _ensure_thought_column(self) -> None:
        """Add ``thought`` string column for assistant reasoning (UI only; not sent to LLM context)."""
        if not self._table_exists():
            return
        table = self.db.open_table(self.table_name)
        if "thought" in table.schema.names:
            return
        rows = table.to_pandas().to_dict(orient="records")
        augmented: list[dict] = []
        for row in rows:
            vec = row.get("vector")
            content = row.get("content", "") or ""
            augmented.append(
                {
                    "id": row.get("id") or str(uuid.uuid4()),
                    "vector": self._normalize_vector(vec, content),
                    "session_id": row.get("session_id") or self.session_id,
                    "role": row.get("role") or "user",
                    "content": content,
                    "timestamp": row.get("timestamp") or self._format_timestamp(),
                    "timestamp_num": int(
                        self._parse_timestamp_num(
                            row.get("timestamp_num"),
                            row.get("timestamp"),
                            self._current_timestamp_num(),
                        )
                    ),
                    "thought": str(row.get("thought") or ""),
                }
            )
        self.db.drop_table(self.table_name, ignore_missing=True)
        if augmented:
            self.db.create_table(self.table_name, data=augmented)

    def _init_session_table(self):
        if not self._has_table(self.session_table_name):
            bootstrap_rows = self._bootstrap_session_rows()
            if bootstrap_rows:
                self.db.create_table(self.session_table_name, data=bootstrap_rows)
            return

        table = self.db.open_table(self.session_table_name)
        schema_fields = set(table.schema.names)
        required_fields = {
            "session_id",
            "title",
            "status",
            "is_pinned",
            "created_at",
            "created_at_num",
            "updated_at",
            "updated_at_num",
            "last_message_at",
            "last_message_at_num",
            "message_count",
        }

        if required_fields.issubset(schema_fields):
            return

        self._migrate_session_table(table)

    def _migrate_session_table(self, table):
        rows = table.to_pandas().to_dict(orient="records")
        existing = {str(row.get("session_id")): row for row in rows if row.get("session_id")}
        migrated_rows = []
        fallback_timestamp_num = self._current_timestamp_num()

        for bootstrap_row in self._bootstrap_session_rows():
            current = existing.get(bootstrap_row["session_id"], {})
            migrated_rows.append(
                {
                    "session_id": bootstrap_row["session_id"],
                    "title": (current.get("title") or bootstrap_row["title"]).strip() or DEFAULT_SESSION_TITLE,
                    "status": self._normalize_session_status(current.get("status") or bootstrap_row["status"]),
                    "is_pinned": bool(current.get("is_pinned", bootstrap_row["is_pinned"])),
                    "created_at": current.get("created_at") or bootstrap_row["created_at"],
                    "created_at_num": int(current.get("created_at_num", bootstrap_row["created_at_num"])),
                    "updated_at": current.get("updated_at") or bootstrap_row["updated_at"],
                    "updated_at_num": int(current.get("updated_at_num", bootstrap_row["updated_at_num"])),
                    "last_message_at": current.get("last_message_at") or bootstrap_row["last_message_at"],
                    "last_message_at_num": int(
                        current.get("last_message_at_num", bootstrap_row["last_message_at_num"])
                    ),
                    "message_count": int(current.get("message_count", bootstrap_row["message_count"])),
                }
            )

        for session_id, row in existing.items():
            if any(item["session_id"] == session_id for item in migrated_rows):
                continue

            migrated_rows.append(
                {
                    "session_id": session_id,
                    "title": (str(row.get("title", "")).strip() or DEFAULT_SESSION_TITLE),
                    "status": self._normalize_session_status(row.get("status") or ACTIVE_SESSION_STATUS),
                    "is_pinned": bool(row.get("is_pinned", False)),
                    "created_at": row.get("created_at") or self._format_timestamp(),
                    "created_at_num": int(row.get("created_at_num", fallback_timestamp_num)),
                    "updated_at": row.get("updated_at") or row.get("created_at") or self._format_timestamp(),
                    "updated_at_num": int(row.get("updated_at_num", row.get("created_at_num", fallback_timestamp_num))),
                    "last_message_at": row.get("last_message_at") or "",
                    "last_message_at_num": int(row.get("last_message_at_num", 0)),
                    "message_count": int(row.get("message_count", 0)),
                }
            )

        self.db.drop_table(self.session_table_name, ignore_missing=True)
        if migrated_rows:
            self.db.create_table(self.session_table_name, data=migrated_rows)

    def _bootstrap_session_rows(self):
        rows = self._query_message_rows()
        sessions = {}
        for row in rows:
            session_id = str(row["session_id"])
            timestamp = row["timestamp"]
            timestamp_num = int(row["timestamp_num"])
            entry = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "title": DEFAULT_SESSION_TITLE,
                    "status": ACTIVE_SESSION_STATUS,
                    "is_pinned": False,
                    "created_at": timestamp,
                    "created_at_num": timestamp_num,
                    "updated_at": timestamp,
                    "updated_at_num": timestamp_num,
                    "last_message_at": timestamp,
                    "last_message_at_num": timestamp_num,
                    "message_count": 0,
                },
            )
            entry["message_count"] += 1
            if timestamp_num < entry["created_at_num"]:
                entry["created_at"] = timestamp
                entry["created_at_num"] = timestamp_num
            if timestamp_num >= entry["last_message_at_num"]:
                entry["last_message_at"] = timestamp
                entry["last_message_at_num"] = timestamp_num
                entry["updated_at"] = timestamp
                entry["updated_at_num"] = timestamp_num
            if entry["title"] == DEFAULT_SESSION_TITLE and row.get("role") == "user":
                entry["title"] = self._derive_session_title(row.get("content", ""))
        return list(sessions.values())

    def _format_timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

    def _current_timestamp_num(self):
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def _current_system_prompt(self):
        return get_effective_system_prompt(self.session_id)

    def get_system_message(self):
        return {"role": "system", "content": self._current_system_prompt()}

    def _table_exists(self):
        return self._has_table(self.table_name)

    def _open_table(self):
        return self.db.open_table(self.table_name)

    def _session_table_exists(self):
        return self._has_table(self.session_table_name)

    def _open_session_table(self):
        return self.db.open_table(self.session_table_name)

    def _escape_where_value(self, value: str):
        return value.replace("\\", "\\\\").replace("'", "''")

    def _build_where_clause(self, field: str, value: str):
        return f"{field} = '{self._escape_where_value(value)}'"

    def _serialize_message(self, row):
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "thought": str(row.get("thought") or ""),
            "timestamp": row["timestamp"],
            "timestamp_num": int(row["timestamp_num"]),
        }

    def _serialize_session(self, row):
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "status": row["status"],
            "is_pinned": bool(row["is_pinned"]),
            "created_at": row["created_at"],
            "created_at_num": int(row["created_at_num"]),
            "updated_at": row["updated_at"],
            "updated_at_num": int(row["updated_at_num"]),
            "last_message_at": row["last_message_at"],
            "last_message_at_num": int(row["last_message_at_num"]),
            "message_count": int(row["message_count"]),
        }

    def _query_message_rows(self, where_clause: str | None = None, limit: int | None = None, offset: int = 0):
        if not self._table_exists():
            return []

        table = self._open_table()
        query = table.search(query=None, ordering_field_name="timestamp_num")
        if where_clause:
            query = query.where(where_clause)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.to_list()

    def _query_session_rows(self, where_clause: str | None = None, limit: int | None = None):
        if not self._session_table_exists():
            return []

        table = self._open_session_table()
        query = table.search(query=None, ordering_field_name="updated_at_num")
        if where_clause:
            query = query.where(where_clause)
        if limit is not None:
            query = query.limit(limit)
        return query.to_list()

    def _substring_search_rows(self, query: str, session_id: str | None = None, limit: int = 5):
        lowered = query.strip().lower()
        if not lowered:
            return []

        where_clause = self._build_where_clause("session_id", session_id) if session_id else None
        rows = self._query_message_rows(where_clause=where_clause)
        matches = [row for row in rows if lowered in str(row.get("content", "")).lower()]
        matches.sort(key=lambda row: row.get("timestamp_num", 0), reverse=True)
        return matches[:limit]

    def _normalize_session_status(self, status: str):
        return normalize_session_status(status)

    def _normalize_session_title(self, title: str | None):
        return normalize_session_title(title)

    def _derive_session_title(self, content: str):
        return derive_session_title(content)

    def _put_session_row(self, row):
        if self._session_table_exists():
            table = self._open_session_table()
            table.delete(self._build_where_clause("session_id", row["session_id"]))
            table.add([row])
        else:
            try:
                self.db.create_table(self.session_table_name, data=[row])
            except Exception:
                table = self._open_session_table()
                table.delete(self._build_where_clause("session_id", row["session_id"]))
                table.add([row])

    def _get_session_row(self, session_id: str):
        rows = self._query_session_rows(
            where_clause=self._build_where_clause("session_id", session_id),
            limit=1,
        )
        if not rows:
            return None
        return rows[0]

    def _ensure_session_row(self, session_id: str):
        existing = self._get_session_row(session_id)
        if existing is not None:
            return existing

        timestamp = self._format_timestamp()
        timestamp_num = self._current_timestamp_num()
        row = {
            "session_id": session_id,
            "title": DEFAULT_SESSION_TITLE,
            "status": ACTIVE_SESSION_STATUS,
            "is_pinned": False,
            "created_at": timestamp,
            "created_at_num": timestamp_num,
            "updated_at": timestamp,
            "updated_at_num": timestamp_num,
            "last_message_at": "",
            "last_message_at_num": 0,
            "message_count": 0,
        }
        self._put_session_row(row)
        return row

    def _refresh_session_stats(self, session_id: str, title_candidate: str | None = None):
        session = self._ensure_session_row(session_id)
        rows = self._query_message_rows(where_clause=self._build_where_clause("session_id", session_id))
        now = self._format_timestamp()
        now_num = self._current_timestamp_num()
        updated = dict(session)

        if rows:
            latest = max(rows, key=lambda row: int(row.get("timestamp_num", 0)))
            first_user = next((row for row in rows if row.get("role") == "user"), None)
            title = session["title"]
            if title == DEFAULT_SESSION_TITLE:
                source = title_candidate or (first_user.get("content", "") if first_user else "")
                title = self._derive_session_title(source)

            updated.update(
                {
                    "title": title,
                    "message_count": len(rows),
                    "last_message_at": latest["timestamp"],
                    "last_message_at_num": int(latest["timestamp_num"]),
                    "updated_at": now,
                    "updated_at_num": now_num,
                }
            )
        else:
            updated.update(
                {
                    "message_count": 0,
                    "last_message_at": "",
                    "last_message_at_num": 0,
                    "updated_at": now,
                    "updated_at_num": now_num,
                }
            )

        self._put_session_row(updated)
        return updated

    def _parse_timestamp_num(self, timestamp_num, timestamp, fallback):
        if timestamp_num is not None:
            return int(timestamp_num)

        try:
            parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %A")
            return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except (TypeError, ValueError):
            return fallback

    def _normalize_vector(self, vector, content: str):
        if vector is None:
            return self._get_embedding(content)
        if hasattr(vector, "tolist"):
            return vector.tolist()
        return list(vector)

    def _check_embedding_available(self) -> bool:
        if not self.embed_model or self._embed_provider is None:
            return False

        config = load_model_config()
        if config.embedding_provider == "ollama":
            from mirai.core.assets_check import assets_check

            return assets_check()

        return True

    def _check_embedding_dim_migration(self) -> None:
        """Detect vector dimension mismatch and trigger migration if needed."""
        if not self._embedding_available or not self.embed_model:
            return
        if not self._has_table(self.table_name):
            return

        table = self.db.open_table(self.table_name)
        rows = table.search(query=None, ordering_field_name="timestamp_num").limit(1).to_list()
        if not rows:
            return

        existing_vec = rows[0].get("vector")
        if existing_vec is None:
            return

        if hasattr(existing_vec, "tolist"):
            existing_vec = existing_vec.tolist()
        existing_dim = len(existing_vec)

        try:
            test_vec = self._embed_provider.embed(self.embed_model, "dimension test")
            new_dim = len(test_vec)
        except Exception:
            return

        if existing_dim == new_dim:
            if all(v == 0.0 for v in existing_vec):
                logger.info(
                    "Detected incomplete migration (zero-vectors with dim=%s). Resuming background re-embed.",
                    new_dim,
                )
                self._fallback_vector_size = new_dim
                self._embedding_available = False
                thread = threading.Thread(
                    target=self._background_re_embed,
                    args=(new_dim,),
                    name="mirai-reembed",
                    daemon=True,
                )
                thread.start()
                return

            config = load_model_config()
            if config.embedding_dim != new_dim:
                config.embedding_dim = new_dim
                save_model_config(config)
            return

        self._fallback_vector_size = new_dim
        logger.info(
            "Embedding dimension changed (%s -> %s). Rebuilding vectors in background.",
            existing_dim,
            new_dim,
        )
        self._rebuild_with_zero_vectors(new_dim)

        config = load_model_config()
        config.embedding_dim = new_dim
        save_model_config(config)

        thread = threading.Thread(
            target=self._background_re_embed,
            args=(new_dim,),
            name="mirai-reembed",
            daemon=True,
        )
        thread.start()

    def _rebuild_with_zero_vectors(self, dim: int) -> None:
        """Rebuild the message table with zero-vectors of the given dimension."""
        if not self._has_table(self.table_name):
            return

        table = self.db.open_table(self.table_name)
        all_rows = table.to_pandas().to_dict(orient="records")
        zero_vec = [0.0] * dim

        rebuilt = []
        for row in all_rows:
            rebuilt.append(
                {
                    "id": row["id"],
                    "vector": zero_vec,
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "thought": str(row.get("thought") or ""),
                    "timestamp": row["timestamp"],
                    "timestamp_num": int(row["timestamp_num"]),
                }
            )

        self.db.drop_table(self.table_name, ignore_missing=True)
        if rebuilt:
            self.db.create_table(self.table_name, data=rebuilt)
        self._embedding_available = False

    def _background_re_embed(self, dim: int) -> None:
        """Re-embed all messages in a background thread.

        Uses LanceDB's ``update`` API to modify vectors in-place,
        avoiding the fragment explosion caused by per-row delete+add
        on a columnar store.  After the main pass, an incremental sweep
        catches messages inserted during the rebuild (they carry zero
        vectors because ``_embedding_available`` was ``False``).
        A compaction pass runs last to consolidate version files.
        """
        try:
            task_start_ts = self._current_timestamp_num()

            db = lancedb.connect(self.db_dir)
            if not self._has_table(self.table_name, db):
                return

            table = db.open_table(self.table_name)
            all_rows = table.to_pandas().to_dict(orient="records")
            snapshot_ids = {row["id"] for row in all_rows}

            updated_count = 0
            skipped = 0
            for row in all_rows:
                vec = row.get("vector")
                if hasattr(vec, "tolist"):
                    vec = vec.tolist()
                if vec and any(v != 0.0 for v in vec):
                    skipped += 1
                    continue

                content = row.get("content", "") or ""
                row_id = row["id"]
                try:
                    vector = self._embed_provider.embed(self.embed_model, content)
                except Exception:
                    vector = [0.0] * dim

                try:
                    table.update(
                        where=f"id = '{self._escape_where_value(row_id)}'",
                        values={"vector": vector},
                    )
                    updated_count += 1
                except Exception as row_exc:
                    logger.warning("Failed to re-embed row %s: %s", row_id, row_exc)

            try:
                table = db.open_table(self.table_name)
                new_rows = (
                    table.search(query=None, ordering_field_name="timestamp_num")
                    .where(f"timestamp_num >= {task_start_ts}")
                    .to_list()
                )
                sweep_count = 0
                for row in new_rows:
                    if row["id"] in snapshot_ids:
                        continue
                    vec = row.get("vector")
                    if vec is not None and hasattr(vec, "tolist"):
                        vec = vec.tolist()
                    if vec and any(v != 0.0 for v in vec):
                        continue
                    content = row.get("content", "") or ""
                    try:
                        vector = self._embed_provider.embed(self.embed_model, content)
                        table.update(
                            where=f"id = '{self._escape_where_value(row['id'])}'",
                            values={"vector": vector},
                        )
                        sweep_count += 1
                    except Exception as sweep_row_exc:
                        logger.debug("Incremental sweep row skip: %s", sweep_row_exc)
                if sweep_count:
                    logger.info("Incremental sweep: re-embedded %s new message(s).", sweep_count)
            except Exception as sweep_exc:
                logger.warning("Incremental sweep failed (non-fatal): %s", sweep_exc)

            try:
                table.compact_files()
                table.cleanup_old_versions()
            except Exception as compact_exc:
                logger.warning("Post-reembed compaction failed (non-fatal): %s", compact_exc)

            self._embedding_available = True
            msg = f"[Memory] Re-embedding complete. {updated_count} updated"
            if skipped:
                msg += f", {skipped} skipped (already valid)"
            logger.info("%s.", msg)

        except Exception:
            logger.exception("Background re-embedding failed")

    def _get_embedding(self, text: str):
        if not self.embed_model or not self._embedding_available or self._embed_provider is None:
            return [0.0] * self._fallback_vector_size

        try:
            return self._embed_provider.embed(self.embed_model, text)
        except Exception as e:
            logger.warning("Embedding generation failed: %s", e)
            self._embedding_available = False
            return [0.0] * self._fallback_vector_size

    def _search_structured_table(
        self,
        table_name: str,
        query: str,
        *,
        limit: int = 8,
        content_field: str = "content",
    ) -> list[dict]:
        if not self._has_table(table_name):
            return []
        normalized_query = (query or "").strip()
        if not normalized_query:
            return []

        query_vector = self._get_embedding(normalized_query)
        rows: list[dict]
        if self.embed_model and self._embedding_available and not _is_degenerate_vector(query_vector):
            try:
                rows = self.db.open_table(table_name).search(query_vector).limit(limit).to_list()
            except Exception as exc:
                logger.debug("Structured vector search failed for %s: %s", table_name, exc)
                rows = []
        else:
            rows = []

        if rows:
            return rows

        lowered = normalized_query.lower()
        all_rows = query_rows(
            self,
            table_name,
            ordering_field_name="updated_at_num" if table_name != self.tool_observation_table_name else "timestamp_num",
        )
        from mirai.core.memories.retrieval import keyword_score

        matches = [
            row
            for row in all_rows
            if lowered in str(row.get(content_field, "")).lower()
            or keyword_score(normalized_query, str(row.get(content_field, ""))) > 0
        ]
        matches.sort(
            key=lambda row: int(
                row.get("updated_at_num") or row.get("timestamp_num") or row.get("created_at_num") or 0
            ),
            reverse=True,
        )
        return matches[:limit]

    def get_session_summary(self, session_id: str | None = None):
        sid = (session_id or self.session_id).strip() or self.session_id
        rows = query_rows(
            self,
            self.session_summary_table_name,
            where_clause=self._build_where_clause("session_id", sid),
            limit=1,
        )
        return rows[0] if rows else None

    def update_session_summary(
        self,
        summary: str,
        session_id: str | None = None,
        *,
        covered_until_num: int | None = None,
    ):
        normalized = " ".join(str(summary or "").split())
        if not normalized:
            raise ValueError("Session summary cannot be empty.")
        sid = (session_id or self.session_id).strip() or self.session_id
        now = self._format_timestamp()
        now_num = self._current_timestamp_num()
        existing = self.get_session_summary(sid) or {}
        row = {
            "session_id": sid,
            "summary": normalized,
            "vector": self._get_embedding(normalized),
            "covered_until_num": int(covered_until_num if covered_until_num is not None else now_num),
            "created_at": existing.get("created_at") or now,
            "created_at_num": int(existing.get("created_at_num") or now_num),
            "updated_at": now,
            "updated_at_num": now_num,
        }
        replace_row(self, self.session_summary_table_name, "session_id", sid, row)
        return row

    def create_long_term_memory(
        self,
        *,
        kind: str,
        content: str,
        session_id: str | None = None,
        source_message_ids: list[str] | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
    ):
        normalized_kind = str(kind or "fact").strip().lower()
        if normalized_kind not in LONG_TERM_MEMORY_KINDS:
            raise ValueError(f"Memory kind must be one of: {', '.join(sorted(LONG_TERM_MEMORY_KINDS))}.")
        normalized_content = " ".join(str(content or "").split())
        if not normalized_content:
            raise ValueError("Long-term memory content cannot be empty.")
        sid = (session_id or self.session_id).strip() or self.session_id
        now = self._format_timestamp()
        now_num = self._current_timestamp_num()
        existing = self._find_long_term_duplicate(normalized_kind, normalized_content, sid)
        row_id = existing.get("id") if existing else str(uuid.uuid4())
        row = {
            "id": row_id,
            "vector": self._get_embedding(normalized_content),
            "kind": normalized_kind,
            "content": normalized_content,
            "source_message_ids": encode_json([x for x in (source_message_ids or []) if x]),
            "session_id": sid,
            "confidence": float(max(0.0, min(1.0, confidence))),
            "importance": float(max(0.0, min(1.0, importance))),
            "created_at": existing.get("created_at") if existing else now,
            "created_at_num": int(existing.get("created_at_num") or now_num) if existing else now_num,
            "updated_at": now,
            "updated_at_num": now_num,
            "last_used_at": str(existing.get("last_used_at") or "") if existing else "",
            "last_used_at_num": int(existing.get("last_used_at_num") or 0) if existing else 0,
        }
        if existing:
            replace_row(self, self.long_term_table_name, "id", row_id, row)
        else:
            add_row(self, self.long_term_table_name, row)
        return self._serialize_long_term_memory(row)

    def _find_long_term_duplicate(self, kind: str, content: str, session_id: str):
        if not self._has_table(self.long_term_table_name):
            return None
        normalized = " ".join(content.lower().split())
        rows = query_rows(
            self,
            self.long_term_table_name,
            where_clause=self._build_where_clause("kind", kind),
        )
        for row in rows:
            if str(row.get("session_id") or "") != session_id:
                continue
            if " ".join(str(row.get("content") or "").lower().split()) == normalized:
                return row
        return None

    def list_long_term_memories(self, kind: str | None = None, session_id: str | None = None, limit: int = 50):
        where_clause = self._build_where_clause("kind", kind.strip().lower()) if kind else None
        rows = query_rows(
            self,
            self.long_term_table_name,
            ordering_field_name="updated_at_num",
            where_clause=where_clause,
            limit=limit,
        )
        if session_id is not None:
            rows = [row for row in rows if str(row.get("session_id") or "") == session_id]
        rows.sort(key=lambda row: int(row.get("updated_at_num") or 0), reverse=True)
        return [self._serialize_long_term_memory(row) for row in rows[:limit]]

    def _serialize_long_term_memory(self, row):
        return {
            "id": row["id"],
            "kind": row["kind"],
            "content": row["content"],
            "source_message_ids": decode_json_list(row.get("source_message_ids")),
            "session_id": row["session_id"],
            "confidence": float(row.get("confidence") or 0.0),
            "importance": float(row.get("importance") or 0.0),
            "created_at": row["created_at"],
            "created_at_num": int(row["created_at_num"]),
            "updated_at": row["updated_at"],
            "updated_at_num": int(row["updated_at_num"]),
            "last_used_at": str(row.get("last_used_at") or ""),
            "last_used_at_num": int(row.get("last_used_at_num") or 0),
        }

    def create_tool_observation(
        self,
        *,
        tool_name: str,
        args_summary: str = "",
        result_summary: str,
        success: bool = True,
        session_id: str | None = None,
        call_id: str = "",
        importance: float = 0.5,
    ):
        normalized_result = " ".join(str(result_summary or "").split())
        if not normalized_result:
            return None
        sid = (session_id or self.session_id).strip() or self.session_id
        now = self._format_timestamp()
        now_num = self._current_timestamp_num()
        name = (tool_name or "tool").strip() or "tool"
        args = " ".join(str(args_summary or "").split())
        content = f"{name}({args}) -> {normalized_result}" if args else f"{name} -> {normalized_result}"
        row = {
            "id": str(uuid.uuid4()),
            "vector": self._get_embedding(content),
            "tool_name": name,
            "args_summary": args,
            "result_summary": normalized_result,
            "content": content,
            "success": bool(success),
            "session_id": sid,
            "call_id": str(call_id or ""),
            "importance": float(max(0.0, min(1.0, importance))),
            "timestamp": now,
            "timestamp_num": now_num,
        }
        add_row(self, self.tool_observation_table_name, row)
        return self._serialize_tool_observation(row)

    def list_tool_observations(self, session_id: str | None = None, limit: int = 50):
        rows = query_rows(
            self,
            self.tool_observation_table_name,
            ordering_field_name="timestamp_num",
            limit=limit,
        )
        if session_id is not None:
            rows = [row for row in rows if str(row.get("session_id") or "") == session_id]
        rows.sort(key=lambda row: int(row.get("timestamp_num") or 0), reverse=True)
        return [self._serialize_tool_observation(row) for row in rows[:limit]]

    def _serialize_tool_observation(self, row):
        return {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "args_summary": row.get("args_summary") or "",
            "result_summary": row["result_summary"],
            "content": row.get("content") or row["result_summary"],
            "success": bool(row.get("success", True)),
            "session_id": row["session_id"],
            "call_id": row.get("call_id") or "",
            "importance": float(row.get("importance") or 0.0),
            "timestamp": row["timestamp"],
            "timestamp_num": int(row["timestamp_num"]),
        }

    def add_message(self, role: str, content: str, thought: str | None = None):
        timestamp = self._format_timestamp()
        timestamp_num = self._current_timestamp_num()
        return self.create_message(
            session_id=self.session_id,
            role=role,
            content=content,
            thought=thought,
            timestamp=timestamp,
            timestamp_num=timestamp_num,
        )["id"]

    def persist_openai_messages(self, messages: list[dict]) -> None:
        """Persist assistant+tool_calls and tool rows so ``get_context`` can replay them."""
        _tool_replay_persist(self, messages)
        try:
            from mirai.core.memories.writer import MemoryWriter

            MemoryWriter(self).observe_tool_turns(messages)
        except Exception as exc:
            logger.debug("Structured tool observation write skipped: %s", exc)

    def get_context(self, query: str = None, max_cross_session: int | None = None):
        from mirai.core.memories.context import ContextBuilder

        return ContextBuilder(self).build(query=query, max_cross_session=max_cross_session)

    def get_recent_messages(self):
        context = self.get_context()
        return context[1:]

    def search_memory(self, query: str, limit: int = 5):
        return self.search_messages(query=query, session_id=self.session_id, limit=limit)

    def clear_history(self):
        if self._table_exists():
            table = self._open_table()
            table.delete(self._build_where_clause("session_id", self.session_id))
        self._refresh_session_stats(self.session_id)

    def delete_message(self, message_id: str):
        existing = self.get_message(message_id)
        if existing is None:
            return False

        self._open_table().delete(self._build_where_clause("id", message_id))
        self._refresh_session_stats(existing["session_id"])
        return True

    def list_messages(
        self,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted_sessions: bool = True,
    ):
        where_clause = self._build_where_clause("session_id", session_id) if session_id else None
        rows = self._query_message_rows(where_clause=where_clause, limit=limit, offset=offset)
        if not include_deleted_sessions and session_id is None:
            deleted_session_ids = {
                session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)
            }
            rows = [row for row in rows if row["session_id"] not in deleted_session_ids]
        return [self._serialize_message(row) for row in rows]

    def get_message(self, message_id: str):
        rows = self._query_message_rows(
            where_clause=self._build_where_clause("id", message_id),
            limit=1,
        )
        if not rows:
            return None
        return self._serialize_message(rows[0])

    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str | None = None,
        timestamp_num: int | None = None,
        message_id: str | None = None,
        thought: str | None = None,
    ):
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")

        normalized_role = role.strip().lower()
        if normalized_role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Memory role must be one of: system, user, assistant, tool.")

        normalized_session_id = session_id.strip() or self.session_id
        from mirai.core.plugins import get_memory_factory

        get_memory_factory().assert_quota_for_session(normalized_session_id)
        existing_session = self._ensure_session_row(normalized_session_id)
        if existing_session["status"] == DELETED_SESSION_STATUS:
            self.update_session(normalized_session_id, status=ACTIVE_SESSION_STATUS)

        thought_val = ""
        if normalized_role == "assistant" and thought is not None and str(thought).strip():
            thought_val = str(thought).strip()

        row = {
            "id": message_id or str(uuid.uuid4()),
            "vector": self._get_embedding(normalized_content),
            "session_id": normalized_session_id,
            "role": normalized_role,
            "content": normalized_content,
            "thought": thought_val,
            "timestamp": timestamp or self._format_timestamp(),
            "timestamp_num": timestamp_num if timestamp_num is not None else self._current_timestamp_num(),
        }

        if self._table_exists():
            self._open_table().add([row])
        else:
            try:
                self.db.create_table(self.table_name, data=[row])
            except Exception:
                self._open_table().add([row])

        self._refresh_session_stats(
            normalized_session_id,
            title_candidate=normalized_content if normalized_role == "user" else None,
        )
        try:
            from mirai.core.plugins import get_memory_factory, get_session_scope

            owner = get_session_scope().owner_user_from_session_id(normalized_session_id)
            get_memory_factory().invalidate_size_cache(owner)
        except Exception:
            pass
        serialized = self._serialize_message(row)
        try:
            from mirai.core.memories.writer import MemoryWriter

            MemoryWriter(self).observe_message(serialized)
        except Exception as exc:
            logger.debug("Structured memory write skipped: %s", exc)
        return serialized

    def update_message(self, message_id: str, content: str, role: str | None = None):
        existing = self.get_message(message_id)
        if existing is None:
            return None

        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")

        updated_role = role.strip().lower() if role is not None else existing["role"]
        if updated_role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Memory role must be one of: system, user, assistant, tool.")

        self.delete_message(message_id)
        updated = self.create_message(
            session_id=existing["session_id"],
            role=updated_role,
            content=normalized_content,
            timestamp=self._format_timestamp(),
            timestamp_num=self._current_timestamp_num(),
            message_id=existing["id"],
            thought=existing.get("thought") or None,
        )
        return updated

    def search_messages(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
        include_deleted_sessions: bool = True,
    ):
        return self._legacy_search_messages(
            query=query,
            session_id=session_id,
            limit=limit,
            include_deleted_sessions=include_deleted_sessions,
        )

    def _legacy_search_messages(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
        include_deleted_sessions: bool = True,
    ):
        if not self._table_exists():
            return []

        normalized_query = query.strip()
        if not normalized_query:
            return []

        if not self.embed_model or not self._embedding_available:
            rows = self._substring_search_rows(normalized_query, session_id=session_id, limit=limit)
            messages = [self._serialize_message(row) for row in rows]
            if include_deleted_sessions or session_id is not None:
                return messages
            deleted_session_ids = {
                session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)
            }
            return [message for message in messages if message["session_id"] not in deleted_session_ids]

        query_vector = self._get_embedding(normalized_query)
        if _is_degenerate_vector(query_vector):
            rows = self._substring_search_rows(normalized_query, session_id=session_id, limit=limit)
            messages = [self._serialize_message(row) for row in rows]
            if include_deleted_sessions or session_id is not None:
                return messages
            deleted_session_ids = {
                session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)
            }
            return [message for message in messages if message["session_id"] not in deleted_session_ids]

        table = self._open_table()
        search = table.search(query_vector)
        if session_id:
            search = search.where(self._build_where_clause("session_id", session_id))
        rows = search.limit(limit).to_list()
        messages = [self._serialize_message(row) for row in rows]
        if include_deleted_sessions or session_id is not None:
            return messages
        deleted_session_ids = {session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)}
        return [message for message in messages if message["session_id"] not in deleted_session_ids]

    def build_related_memory_message(self, query: str, exclude_session_id: str | None = None, limit: int = 5):
        if not query or not query.strip():
            return None

        related = self.search_messages(query=query, session_id=None, limit=limit)
        seen = set()
        lines = ["Relevant memory from previous chats:"]

        for item in related:
            if exclude_session_id and item["session_id"] == exclude_session_id:
                continue

            normalized_content = " ".join(item["content"].split())
            dedupe_key = (item["session_id"], item["role"], normalized_content.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            lines.append(f"- [{item['session_id']}] ({item['role']}, {item['timestamp']}) {normalized_content[:240]}")

        if len(lines) == 1:
            return None

        return {
            "role": "system",
            "content": "\n".join(lines),
        }

    def create_session(self, title: str | None = None, session_id: str | None = None):
        normalized_session_id = (session_id or "").strip() or str(uuid.uuid4())
        existing = self.get_session(normalized_session_id)
        if existing is not None:
            return existing

        timestamp = self._format_timestamp()
        timestamp_num = self._current_timestamp_num()
        row = {
            "session_id": normalized_session_id,
            "title": self._normalize_session_title(title),
            "status": ACTIVE_SESSION_STATUS,
            "is_pinned": False,
            "created_at": timestamp,
            "created_at_num": timestamp_num,
            "updated_at": timestamp,
            "updated_at_num": timestamp_num,
            "last_message_at": "",
            "last_message_at_num": 0,
            "message_count": 0,
        }
        self._put_session_row(row)
        return self._serialize_session(row)

    def get_session(self, session_id: str):
        row = self._get_session_row(session_id)
        if row is None:
            return None
        return self._serialize_session(row)

    def update_session(
        self,
        session_id: str,
        title: str | None = None,
        is_pinned: bool | None = None,
        status: str | None = None,
    ):
        existing = self._get_session_row(session_id)
        if existing is None:
            return None

        updated = dict(existing)
        updated["title"] = self._normalize_session_title(title) if title is not None else existing["title"]
        updated["is_pinned"] = bool(is_pinned) if is_pinned is not None else bool(existing["is_pinned"])
        updated["status"] = (
            self._normalize_session_status(status)
            if status is not None
            else self._normalize_session_status(existing["status"])
        )
        updated["updated_at"] = self._format_timestamp()
        updated["updated_at_num"] = self._current_timestamp_num()
        self._put_session_row(updated)
        return self._serialize_session(updated)

    def list_sessions(self, status: str = ACTIVE_SESSION_STATUS, session_id_prefix: str | None = None):
        normalized_status = status.strip().lower()
        if normalized_status not in {ACTIVE_SESSION_STATUS, DELETED_SESSION_STATUS, "all"}:
            raise ValueError("Session status filter must be one of: active, deleted, all.")

        rows = self._query_session_rows()
        sessions = [self._serialize_session(row) for row in rows]
        if session_id_prefix:
            sessions = [s for s in sessions if str(s["session_id"]).startswith(session_id_prefix)]
        if normalized_status != "all":
            sessions = [session for session in sessions if session["status"] == normalized_status]

        sessions.sort(
            key=lambda item: (
                1 if item["is_pinned"] else 0,
                max(item["last_message_at_num"], item["updated_at_num"]),
            ),
            reverse=True,
        )
        return sessions
