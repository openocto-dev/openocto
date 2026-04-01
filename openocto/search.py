"""Semantic search — FTS5 (always) + sqlite-vec (optional)."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openocto.config import MemoryConfig
    from openocto.history import HistoryStore

logger = logging.getLogger(__name__)


def _vector_available() -> bool:
    """Check if vector search dependencies are installed."""
    try:
        import sqlite_vec  # noqa: F401
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


class SemanticSearch:
    """Hybrid search: FTS5 (always) + sqlite-vec (optional).

    Falls back to FTS5-only if vector dependencies are not installed.
    """

    VECTOR_WEIGHT = 0.7
    FTS_WEIGHT = 0.3

    def __init__(self, history: HistoryStore, config: MemoryConfig) -> None:
        self._history = history
        self._half_life_days = config.search_half_life_days
        self._vector_enabled = _vector_available()
        self._embedder = None
        self._vec_initialized = False

        if self._vector_enabled:
            self._init_vector()

    def _init_vector(self) -> None:
        """Initialize vector search (embedding model + sqlite-vec table)."""
        try:
            from fastembed import TextEmbedding
            self._embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            # sqlite-vec table creation would go here
            # For now, vector search is a placeholder — FTS5 is the primary
            self._vec_initialized = True
            logger.info("Vector search initialized (fastembed + sqlite-vec)")
        except Exception:
            logger.warning("Vector search init failed, using FTS5 only", exc_info=True)
            self._vector_enabled = False

    def index_message(self, msg_id: int, text: str) -> None:
        """Index a message for search. FTS5 is handled by HistoryStore.add_message().

        Vector indexing is done here if available.
        """
        if not self._vec_initialized or not self._embedder:
            return

        # Vector indexing placeholder — will be implemented with sqlite-vec tables
        # For now, FTS5 handles all search
        pass

    def search(
        self, query: str, user_id: int, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Search messages using FTS5 + optional vector search.

        Returns messages with temporal decay applied.
        """
        if not query.strip():
            return []

        # FTS5 search
        fts_results = self._history.fts_search(query, user_id, limit=limit * 2)

        # Apply temporal decay
        scored = []
        for r in fts_results:
            decay = self._temporal_decay(r.get("created_at", ""))
            scored.append({**r, "_score": abs(r.get("fts_rank", 0)) * decay})

        # Sort by score (higher = better) and return top N
        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored[:limit]

    def _temporal_decay(self, created_at: str) -> float:
        """Calculate temporal decay factor for a message."""
        if not created_at:
            return 1.0
        try:
            msg_time = datetime.fromisoformat(created_at)
            now = datetime.now(timezone.utc) if msg_time.tzinfo else datetime.now()
            age_days = (now - msg_time).days
            return math.pow(0.5, age_days / max(self._half_life_days, 1))
        except (ValueError, TypeError):
            return 1.0

    @staticmethod
    def vector_available() -> bool:
        """Check if vector search dependencies are installed."""
        return _vector_available()
