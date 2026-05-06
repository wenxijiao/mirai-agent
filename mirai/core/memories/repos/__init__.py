"""Per-table repositories owned by :class:`mirai.core.memories.memory.Memory`.

Each repository:

* owns one LanceDB table (schema, init, migration, CRUD),
* shares the :class:`~mirai.core.memories.backend.LanceDBBackend` so table
  helpers and time/SQL primitives are not duplicated,
* exposes a small public API the :class:`Memory` façade delegates to.

The split exists so enterprise builds can swap LanceDB for another store
(e.g. PostgreSQL via ``mirai_enterprise.tenancy.postgres_store``) by
implementing the same Repository surface without rewriting the façade.
"""

from mirai.core.memories.repos.long_term import LongTermMemoryRepository
from mirai.core.memories.repos.messages import MessageRepository
from mirai.core.memories.repos.observations import ToolObservationRepository
from mirai.core.memories.repos.sessions import SessionRepository
from mirai.core.memories.repos.summaries import SessionSummaryRepository

__all__ = [
    "LongTermMemoryRepository",
    "MessageRepository",
    "SessionRepository",
    "SessionSummaryRepository",
    "ToolObservationRepository",
]
