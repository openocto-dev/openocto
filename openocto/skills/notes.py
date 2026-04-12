"""Notes skill — store conversation notes and user facts via HistoryStore.

Thin wrapper that lets the LLM persist things explicitly when the user
says "remember that…", "note: …", "забудь это" etc.  Notes live in
``conversation_notes`` (per-persona, can be resolved); facts live in
``user_facts`` (global, persistent).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError


class _Params(BaseModel):
    action: Literal["add_note", "add_fact", "list_notes", "list_facts", "resolve_note"] = Field(
        description="What to do: add or list notes/facts, or resolve a note by id.",
    )
    content: str | None = Field(
        default=None,
        description="The note or fact text. Required for add_note / add_fact.",
    )
    category: str = Field(
        default="general",
        description=(
            "Category for facts: 'personal', 'preference', 'work', "
            "'communication_style', etc. For notes: free-form."
        ),
    )
    note_id: int | None = Field(
        default=None,
        description="Note id to resolve (only for resolve_note).",
    )


class NotesSkill(Skill):
    name = "manage_notes_and_facts"
    description = (
        "Save or recall things the user wants you to remember. Use when the "
        "user says 'remember that…', 'запомни что…', 'note that…', 'forget…', "
        "'what do you know about me?', or asks to list saved notes. "
        "Distinguish: a NOTE is short-term/situational (per persona, can be "
        "resolved); a FACT is durable user info (name, preferences, etc.)."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Filled in by registry.bind_context(...)
        self._ctx_history = None
        self._ctx_user_id = None
        self._ctx_persona = None

    async def execute(
        self,
        action: str,
        content: str | None = None,
        category: str = "general",
        note_id: int | None = None,
    ) -> str:
        history = self._ctx_history
        user_id = self._ctx_user_id
        persona = self._ctx_persona or "octo"
        if history is None or user_id is None:
            raise SkillError("notes skill not bound to a user — internal error")

        if action == "add_note":
            if not content:
                raise SkillError("content is required for add_note")
            note_id = history.add_note(user_id, persona, content, category=category)
            return f"Saved note #{note_id}: {content}"

        if action == "add_fact":
            if not content:
                raise SkillError("content is required for add_fact")
            fact_id = history.add_fact(user_id, content, category=category, source="explicit")
            return f"Saved fact #{fact_id} [{category}]: {content}"

        if action == "list_notes":
            notes = history.get_active_notes(user_id, persona)
            if not notes:
                return "No active notes."
            lines = [f"#{n['id']}: {n['note']}" for n in notes[:20]]
            return "\n".join(lines)

        if action == "list_facts":
            facts = history.get_active_facts(user_id)
            if not facts:
                return "No facts known yet."
            lines = [f"[{f['category']}] {f['fact']}" for f in facts[:30]]
            return "\n".join(lines)

        if action == "resolve_note":
            if note_id is None:
                raise SkillError("note_id is required for resolve_note")
            history.resolve_note(note_id)
            return f"Resolved note #{note_id}"

        raise SkillError(f"Unknown action: {action}")
