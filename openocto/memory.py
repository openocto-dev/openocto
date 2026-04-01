"""Memory system — context builder, summarization, fact extraction."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openocto.config import MemoryConfig
    from openocto.history import HistoryStore
    from openocto.persona.manager import Persona
    from openocto.search import SemanticSearch

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_SECTIONS = [
    "Preferences",
    "Active reminders",
    "Ongoing topics",
    "Recent context",
]

_MIN_SUMMARY_LENGTH = 50  # chars — quality guard threshold


class MemoryManager:
    """Builds rich context for AI requests and manages background summarization."""

    def __init__(
        self,
        history: HistoryStore,
        config: MemoryConfig,
        search: SemanticSearch | None = None,
    ) -> None:
        self._history = history
        self._config = config
        self._search = search

    # ── Public API ─────────────────────────────────────────────────────

    def build_context(
        self,
        user_id: int,
        persona: Persona,
        user_text: str,
    ) -> tuple[str, list[dict]]:
        """Build enriched system prompt + recent message history.

        Returns:
            (system_prompt, recent_messages) ready for AI backend.
        """
        parts: list[str] = [persona.system_prompt]

        # User facts
        facts = self._history.get_active_facts(user_id)
        if facts:
            lines = []
            for f in facts[: self._config.max_facts]:
                lines.append(f"[{f['category']}] {f['fact']}")
            parts.append("## What you know about the user\n" + "\n".join(lines))

        # Active notes
        notes = self._history.get_active_notes(user_id, persona.name)
        if notes:
            lines = [n["note"] for n in notes[: self._config.max_notes]]
            parts.append("## Active notes\n" + "\n".join(f"- {line}" for line in lines))

        # Latest summary
        summary = self._history.get_latest_summary(user_id, persona.name)
        if summary:
            parts.append("## Previous conversation context\n" + summary["summary"])

        # Semantic search
        if self._search and user_text.strip():
            results = self._search.search(user_text, user_id, limit=3)
            if results:
                lines = []
                for r in results:
                    date = r.get("created_at", "")[:10]
                    lines.append(f"[{date}] {r['role'].title()}: {r['content']}")
                parts.append("## Relevant past conversations\n" + "\n".join(lines))

        system_prompt = "\n\n".join(parts)

        # Recent messages (short-term window)
        recent = self._history.get_recent_messages(
            user_id, persona.name, limit=self._config.recent_window,
        )

        return system_prompt, recent

    async def maybe_process(
        self,
        user_id: int,
        persona: Persona,
        ai_router,
    ) -> None:
        """Check if summarization is needed and run it in background.

        Should be called after each AI response via asyncio.create_task().
        """
        if not self._config.enabled:
            return

        count = self._history.count_unsummarized(user_id, persona.name)
        threshold = self._config.summarize_threshold + self._config.recent_window

        if count <= threshold:
            return

        logger.info(
            "Memory: %d unsummarized messages (threshold %d), starting extraction",
            count, threshold,
        )

        try:
            await self._run_extraction(user_id, persona, ai_router)
        except Exception:
            logger.exception("Memory extraction failed, will retry next cycle")

    # ── Internal ───────────────────────────────────────────────────────

    async def _run_extraction(
        self,
        user_id: int,
        persona: Persona,
        ai_router,
    ) -> None:
        """Run the 3-in-1 extraction: summary + notes + facts."""
        # Get messages to summarize (everything beyond recent window)
        all_unsummarized = self._history.get_unsummarized_messages(
            user_id, persona.name, limit=500,
        )
        if len(all_unsummarized) <= self._config.recent_window:
            return

        # Messages to summarize = all except the recent window
        to_summarize = all_unsummarized[: -self._config.recent_window]
        if not to_summarize:
            return

        # Gather existing context
        prev_summary = self._history.get_latest_summary(user_id, persona.name)
        active_notes = self._history.get_active_notes(user_id, persona.name)
        existing_facts = self._history.get_active_facts(user_id)
        sections = self._get_summary_sections(persona)

        # Build extraction prompt
        prompt = self._build_extraction_prompt(
            messages=to_summarize,
            prev_summary=prev_summary["summary"] if prev_summary else None,
            notes=[n["note"] for n in active_notes],
            facts=[f"[{ef['category']}] {ef['fact']}" for ef in existing_facts],
            sections=sections,
        )

        # Call AI
        backend = ai_router.get_backend()
        response = await backend.send(
            [{"role": "user", "content": prompt}],
            "You are a memory extraction assistant. Follow the instructions precisely.",
        )

        # Parse response
        summary_text, new_notes, resolved_notes, new_facts = self._parse_response(response)

        # Quality guard
        if not self._validate_summary(summary_text, len(to_summarize)):
            logger.warning("Summary too short (%d chars), retrying once", len(summary_text))
            response = await backend.send(
                [{"role": "user", "content": prompt}],
                "You are a memory extraction assistant. Follow the instructions precisely. "
                "Be thorough — the summary must cover all important topics.",
            )
            summary_text, new_notes, resolved_notes, new_facts = self._parse_response(response)

            if not self._validate_summary(summary_text, len(to_summarize)):
                logger.warning("Summary still too short after retry, skipping")
                return

        # Store summary
        self._history.add_summary(
            user_id=user_id,
            persona=persona.name,
            summary=summary_text,
            from_msg_id=to_summarize[0]["id"],
            to_msg_id=to_summarize[-1]["id"],
            msg_count=len(to_summarize),
        )

        # Update notes
        self._update_notes(user_id, persona.name, new_notes, resolved_notes, active_notes)

        # Update facts
        self._update_facts(user_id, new_facts)

        # Auto-resolve old notes
        resolved_count = self._history.auto_resolve_old_notes(
            user_id, persona.name, self._config.notes_ttl_days,
        )
        if resolved_count:
            logger.info("Auto-resolved %d old notes (TTL=%dd)", resolved_count, self._config.notes_ttl_days)

        logger.info(
            "Memory extraction complete: summary=%d chars, notes=%d, facts=%d",
            len(summary_text), len(new_notes), len(new_facts),
        )

    def _get_summary_sections(self, persona: Persona) -> list[str]:
        """Get summary sections from persona config or defaults."""
        return getattr(persona, "memory_summary_sections", None) or DEFAULT_SUMMARY_SECTIONS

    def _build_extraction_prompt(
        self,
        messages: list[dict],
        prev_summary: str | None,
        notes: list[str],
        facts: list[str],
        sections: list[str],
    ) -> str:
        """Build the 3-in-1 extraction prompt."""
        sections_formatted = "\n".join(f"### {s}" for s in sections)

        conversation = "\n".join(
            f"{m['role'].title()}: {m['content']}" for m in messages
        )

        return f"""\
Analyze the following conversation and provide THREE outputs:

## SUMMARY
Summarize using EXACTLY these sections (skip empty sections):
{sections_formatted}

Write concisely (1-3 sentences per section). Focus on context needed for continuation. Write in the conversation's language.

## NOTES
Extract important items that the summary might lose. One per line.
Types: follow-ups, ongoing topics, emotional context, agreements, reminders.
Mark resolved items from previous notes with "RESOLVED: <note>".
If nothing important, write "None".

## FACTS
Extract personal facts about the user. One fact per line. Tag each with a category:
[personal] User's name is Dmitry
[communication_style] User prefers brief answers and informal tone
[preference] User prefers metric units
[work] User is a software developer
Only include facts explicitly stated or clearly implied.
If no new facts, write "None".

Previous summary: {prev_summary or "None"}
Active notes: {chr(10).join(notes) if notes else "None"}
Known facts: {chr(10).join(facts) if facts else "None"}

Conversation:
{conversation}"""

    def _parse_response(
        self, text: str,
    ) -> tuple[str, list[str], list[str], list[tuple[str, str]]]:
        """Parse extraction response into (summary, new_notes, resolved_notes, facts).

        Facts are returned as (category, fact) tuples.
        """
        # Split by ## markers
        summary_text = ""
        notes_text = ""
        facts_text = ""

        # Find sections
        parts = re.split(r"^## ", text, flags=re.MULTILINE)
        for part in parts:
            lower = part.lower()
            if lower.startswith("summary"):
                summary_text = part[len("summary"):].strip().lstrip("\n")
            elif lower.startswith("notes"):
                notes_text = part[len("notes"):].strip().lstrip("\n")
            elif lower.startswith("facts"):
                facts_text = part[len("facts"):].strip().lstrip("\n")

        # Parse notes
        new_notes = []
        resolved_notes = []
        for line in notes_text.splitlines():
            line = line.strip().lstrip("- ")
            if not line or line.lower() == "none":
                continue
            if line.upper().startswith("RESOLVED:"):
                resolved_notes.append(line[len("RESOLVED:"):].strip())
            else:
                new_notes.append(line)

        # Parse facts with categories
        facts: list[tuple[str, str]] = []
        for line in facts_text.splitlines():
            line = line.strip().lstrip("- ")
            if not line or line.lower() == "none":
                continue
            # Try to extract [category] prefix
            m = re.match(r"\[(\w+)\]\s*(.*)", line)
            if m:
                facts.append((m.group(1), m.group(2)))
            else:
                facts.append(("personal", line))

        return summary_text, new_notes, resolved_notes, facts

    def _validate_summary(self, summary: str, msg_count: int) -> bool:
        """Quality guard: summary should be meaningful for the message count."""
        if msg_count > 20 and len(summary) < _MIN_SUMMARY_LENGTH:
            return False
        return bool(summary.strip())

    def _update_notes(
        self,
        user_id: int,
        persona: str,
        new_notes: list[str],
        resolved_notes: list[str],
        active_notes: list[dict],
    ) -> None:
        """Add new notes and resolve old ones."""
        # Resolve matching notes
        for resolved_text in resolved_notes:
            resolved_lower = resolved_text.lower()
            for note in active_notes:
                if resolved_lower in note["note"].lower():
                    self._history.resolve_note(note["id"])
                    break

        # Add new notes
        for note_text in new_notes:
            self._history.add_note(user_id, persona, note_text)

    def _update_facts(
        self,
        user_id: int,
        new_facts: list[tuple[str, str]],
    ) -> None:
        """Add new facts, deactivating contradicting old ones."""
        existing = self._history.get_active_facts(user_id)

        for category, fact_text in new_facts:
            # Simple deduplication: skip if very similar fact already exists
            duplicate = False
            for existing_fact in existing:
                if (
                    existing_fact["category"] == category
                    and self._facts_similar(existing_fact["fact"], fact_text)
                ):
                    duplicate = True
                    break

            if not duplicate:
                self._history.add_fact(user_id, fact_text, category=category)

    @staticmethod
    def _facts_similar(a: str, b: str) -> bool:
        """Check if two facts are similar enough to be considered duplicates."""
        # Normalize and compare
        a_norm = a.lower().strip().rstrip(".")
        b_norm = b.lower().strip().rstrip(".")
        if a_norm == b_norm:
            return True
        # Check if one contains the other
        if a_norm in b_norm or b_norm in a_norm:
            return True
        return False
