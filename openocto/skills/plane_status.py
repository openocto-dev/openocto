"""Plane status digest skill — read-only project / task summaries.

Why this exists: when you connect Plane through the generic MCP client you
get 100+ CRUD tools, each ~500 tokens of JSON Schema in every LLM request.
For status queries ("what are my tasks", "team workload") that's pure waste:
the LLM has to orchestrate 5 sequential MCP calls and re-format the result
itself.

This skill collapses all that into ONE tool with an enum scope parameter and
a TTS-friendly text output. Credentials are reused from
``~/.openocto/mcp-secrets.yaml`` under server name ``Plane`` so the user
doesn't have to configure them twice.

Required env (all in mcp-secrets.yaml under ``servers.Plane.env``):
    PLANE_API_KEY        — workspace API key
    PLANE_BASE_URL       — e.g. https://workspace.example.com
    PLANE_WORKSPACE_SLUG — e.g. my-team

Optional:
    PLANE_USER_ID        — UUID of the user this assistant runs for
    PLANE_USER_EMAIL     — fallback to resolve user id via /members/

If neither USER_ID nor USER_EMAIL is set, the ``my_tasks`` scope returns
an instructive error and the other scopes still work.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.mcp_client.secrets import MCPSecretsStore
from openocto.skills.base import Skill, SkillError, SkillUnavailable

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_OPEN_GROUPS = {"backlog", "unstarted", "started"}
_MAX_LIST_ITEMS = 8  # truncate long lists in TTS output


# ── Tool parameter schema ────────────────────────────────────────────────────


class _Params(BaseModel):
    scope: Literal["my_tasks", "team_tasks", "team_load", "overdue"] = Field(
        description=(
            "Which report to generate. "
            "'my_tasks' = open tasks assigned to the current user, grouped by project. "
            "'team_tasks' = per-project overview (open / in-progress / overdue counts). "
            "'team_load' = members ranked by number of open assigned tasks. "
            "'overdue' = list of overdue tasks across all projects."
        ),
    )
    project: str | None = Field(
        default=None,
        description=(
            "Optional project name or identifier (e.g. 'PORTAL', 'Bots') "
            "to narrow the scope to one project. Case-insensitive substring match."
        ),
    )


# ── Skill ────────────────────────────────────────────────────────────────────


class PlaneStatusSkill(Skill):
    name = "plane_status"
    description = (
        "Get a HUMAN-READABLE STATUS REPORT from Plane (read-only): your open "
        "tasks, team workload, project overviews, or overdue items. "
        "USE THIS for any 'what are my/our/their tasks', 'how busy is the team', "
        "'what's overdue', 'project status' kind of question. "
        "Do NOT use this to create or update tasks — for that, use plane__create_work_item "
        "or plane__update_work_item."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        secrets = MCPSecretsStore().get_env("Plane")
        self._api_key = secrets.get("PLANE_API_KEY", "").strip()
        self._base_url = secrets.get("PLANE_BASE_URL", "").rstrip("/")
        self._slug = secrets.get("PLANE_WORKSPACE_SLUG", "").strip()
        self._user_id_hint = secrets.get("PLANE_USER_ID", "").strip() or None
        self._user_email = secrets.get("PLANE_USER_EMAIL", "").strip().lower() or None

        if not (self._api_key and self._base_url and self._slug):
            raise SkillUnavailable(
                "Plane credentials missing in mcp-secrets.yaml "
                "(need PLANE_API_KEY, PLANE_BASE_URL, PLANE_WORKSPACE_SLUG)"
            )

        # Caches populated lazily on first call within a process.
        self._members_cache: list[dict[str, Any]] | None = None
        self._user_id_cache: str | None = None
        self._states_cache: dict[str, dict[str, dict[str, Any]]] = {}

        logger.info(
            "PlaneStatusSkill initialized: %s (workspace=%s)",
            self._base_url, self._slug,
        )

    # ── Public dispatch ──────────────────────────────────────────────────

    async def execute(self, scope: str, project: str | None = None) -> str:
        try:
            if scope == "my_tasks":
                return await self._my_tasks(project)
            if scope == "team_tasks":
                return await self._team_tasks(project)
            if scope == "team_load":
                return await self._team_load(project)
            if scope == "overdue":
                return await self._overdue(project)
            raise SkillError(f"Unknown scope: {scope!r}")
        except SkillError:
            raise
        except Exception as exc:
            logger.exception("PlaneStatusSkill failed (scope=%s)", scope)
            raise SkillError(f"Plane request failed: {exc}")

    # ── HTTP layer ───────────────────────────────────────────────────────

    def _request_sync(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Synchronous Plane REST GET — runs inside ``asyncio.to_thread``."""
        import requests

        url = f"{self._base_url}/api/v1/workspaces/{self._slug}/{path.lstrip('/')}"
        try:
            r = requests.get(
                url,
                headers={"X-API-Key": self._api_key, "Accept": "application/json"},
                params=params,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SkillError(f"Plane API unreachable: {exc}")

        if r.status_code == 401:
            raise SkillError("Plane API rejected the credentials (401)")
        if r.status_code == 404:
            raise SkillError(f"Plane endpoint not found: {path}")
        if r.status_code >= 400:
            raise SkillError(f"Plane API error {r.status_code}: {r.text[:120]}")
        try:
            return r.json()
        except ValueError as exc:
            raise SkillError(f"Plane returned non-JSON: {exc}")

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._request_sync, path, params)

    # ── Cached lookups ───────────────────────────────────────────────────

    async def _list_projects(self) -> list[dict[str, Any]]:
        data = await self._request("projects/")
        return data.get("results", []) if isinstance(data, dict) else []

    async def _list_members(self) -> list[dict[str, Any]]:
        if self._members_cache is not None:
            return self._members_cache
        data = await self._request("members/")
        members = data.get("results", data) if isinstance(data, dict) else data
        self._members_cache = members if isinstance(members, list) else []
        return self._members_cache

    async def _resolve_user_id(self) -> str:
        if self._user_id_cache:
            return self._user_id_cache
        if self._user_id_hint:
            self._user_id_cache = self._user_id_hint
            return self._user_id_cache
        if not self._user_email:
            raise SkillError(
                "Cannot determine current user. "
                "Set PLANE_USER_EMAIL or PLANE_USER_ID in mcp-secrets.yaml "
                "under servers.Plane.env"
            )
        members = await self._list_members()
        for m in members:
            if (m.get("email") or "").lower() == self._user_email:
                self._user_id_cache = m.get("id")
                if self._user_id_cache:
                    return self._user_id_cache
        raise SkillError(
            f"User with email {self._user_email!r} not found in workspace members"
        )

    async def _project_states(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Return {state_id: state_dict} for a project (cached per process)."""
        if project_id in self._states_cache:
            return self._states_cache[project_id]
        data = await self._request(f"projects/{project_id}/states/")
        states = data.get("results", data) if isinstance(data, dict) else data
        mapping = {s["id"]: s for s in (states or []) if isinstance(s, dict)}
        self._states_cache[project_id] = mapping
        return mapping

    async def _project_issues(
        self, project_id: str, params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        data = await self._request(f"projects/{project_id}/issues/", params=params)
        return data.get("results", []) if isinstance(data, dict) else []

    # ── Helpers ──────────────────────────────────────────────────────────

    def _filter_projects(
        self, projects: list[dict[str, Any]], needle: str | None,
    ) -> list[dict[str, Any]]:
        if not needle:
            return projects
        n = needle.lower()
        matched = [
            p for p in projects
            if n in (p.get("name") or "").lower()
            or n == (p.get("identifier") or "").lower()
        ]
        return matched or projects  # fall back to all if no match — better UX

    @staticmethod
    def _is_open(issue: dict[str, Any], states: dict[str, dict[str, Any]]) -> bool:
        sid = issue.get("state")
        sgroup = (states.get(sid, {}).get("group") or "").lower()
        return sgroup in _OPEN_GROUPS

    @staticmethod
    def _state_group(issue: dict[str, Any], states: dict[str, dict[str, Any]]) -> str:
        return (states.get(issue.get("state"), {}).get("group") or "").lower()

    @staticmethod
    def _format_count(n: int, one: str, few: str, many: str) -> str:
        """Russian plural: 1 задача, 2-4 задачи, 5+ задач."""
        n_abs = abs(n) % 100
        if 11 <= n_abs <= 14:
            return f"{n} {many}"
        n_last = n_abs % 10
        if n_last == 1:
            return f"{n} {one}"
        if 2 <= n_last <= 4:
            return f"{n} {few}"
        return f"{n} {many}"

    @classmethod
    def _tasks_word(cls, n: int) -> str:
        return cls._format_count(n, "задача", "задачи", "задач")

    @staticmethod
    def _parse_date(s: str | None) -> date | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            return None

    # ── Scope: my_tasks ──────────────────────────────────────────────────

    async def _my_tasks(self, project_filter: str | None) -> str:
        projects = self._filter_projects(await self._list_projects(), project_filter)
        if not projects:
            return "В Plane нет проектов."

        user_id = await self._resolve_user_id()

        async def fetch_one(p: dict[str, Any]) -> tuple[dict, list, dict]:
            issues, states = await asyncio.gather(
                self._project_issues(p["id"], {"assignees": user_id}),
                self._project_states(p["id"]),
            )
            return p, issues, states

        results = await asyncio.gather(*(fetch_one(p) for p in projects))

        per_project: list[tuple[str, int, int]] = []  # (name, open, in_progress)
        urgent: list[str] = []
        total_open = 0
        for p, issues, states in results:
            open_issues = [i for i in issues if self._is_open(i, states)]
            if not open_issues:
                continue
            in_progress = sum(
                1 for i in open_issues if self._state_group(i, states) == "started"
            )
            per_project.append((p["name"], len(open_issues), in_progress))
            total_open += len(open_issues)
            for i in open_issues:
                if (i.get("priority") or "").lower() in ("urgent", "high"):
                    urgent.append(i.get("name", "?"))

        if total_open == 0:
            return "У тебя нет открытых задач в Plane. Чисто!"

        per_project.sort(key=lambda x: -x[1])
        lines = [f"У тебя {self._tasks_word(total_open)} в Plane."]
        if per_project:
            parts = []
            for name, n, started in per_project[:_MAX_LIST_ITEMS]:
                hint = f", {started} в работе" if started else ""
                parts.append(f"{name} — {self._tasks_word(n)}{hint}")
            extra = len(per_project) - _MAX_LIST_ITEMS
            if extra > 0:
                parts.append(f"и ещё {self._tasks_word(extra)} в других проектах")
            lines.append("По проектам: " + "; ".join(parts) + ".")
        if urgent:
            urgent_show = urgent[:3]
            extra = len(urgent) - len(urgent_show)
            tail = f" и ещё {extra}" if extra > 0 else ""
            lines.append(
                f"Срочных {len(urgent)}: «" + "», «".join(urgent_show) + "»" + tail + "."
            )
        return " ".join(lines)

    # ── Scope: team_tasks ────────────────────────────────────────────────

    async def _team_tasks(self, project_filter: str | None) -> str:
        projects = self._filter_projects(await self._list_projects(), project_filter)
        if not projects:
            return "В Plane нет проектов."

        async def fetch_one(p: dict[str, Any]) -> tuple[dict, list, dict]:
            issues, states = await asyncio.gather(
                self._project_issues(p["id"]),
                self._project_states(p["id"]),
            )
            return p, issues, states

        results = await asyncio.gather(*(fetch_one(p) for p in projects))

        today = date.today()
        per_project: list[tuple[str, int, int, int]] = []  # name, open, started, overdue
        for p, issues, states in results:
            open_n = started_n = overdue_n = 0
            for i in issues:
                grp = self._state_group(i, states)
                if grp not in _OPEN_GROUPS:
                    continue
                open_n += 1
                if grp == "started":
                    started_n += 1
                td = self._parse_date(i.get("target_date"))
                if td and td < today:
                    overdue_n += 1
            if open_n:
                per_project.append((p["name"], open_n, started_n, overdue_n))

        if not per_project:
            return "Во всех проектах нет открытых задач."

        per_project.sort(key=lambda x: -x[1])
        total_open = sum(x[1] for x in per_project)
        total_overdue = sum(x[3] for x in per_project)

        lines = [
            f"В команде {self._tasks_word(total_open)} открытых "
            f"в {len(per_project)} {self._format_count(len(per_project), 'проекте', 'проектах', 'проектах')}.",
        ]
        top = per_project[:_MAX_LIST_ITEMS]
        parts = []
        for name, n, started, overdue in top:
            extras = []
            if started:
                extras.append(f"{started} в работе")
            if overdue:
                extras.append(f"{overdue} просрочено")
            tail = f" ({', '.join(extras)})" if extras else ""
            parts.append(f"{name} — {self._tasks_word(n)}{tail}")
        lines.append("Топ проектов: " + "; ".join(parts) + ".")
        if total_overdue and not project_filter:
            lines.append(
                f"Всего просроченных: {self._tasks_word(total_overdue)}."
            )
        return " ".join(lines)

    # ── Scope: team_load ─────────────────────────────────────────────────

    async def _team_load(self, project_filter: str | None) -> str:
        projects = self._filter_projects(await self._list_projects(), project_filter)
        members = await self._list_members()
        if not projects:
            return "В Plane нет проектов."
        if not members:
            return "В команде нет участников."

        async def fetch_one(p: dict[str, Any]) -> tuple[list, dict]:
            issues, states = await asyncio.gather(
                self._project_issues(p["id"]),
                self._project_states(p["id"]),
            )
            return issues, states

        results = await asyncio.gather(*(fetch_one(p) for p in projects))

        load: dict[str, int] = {}
        for issues, states in results:
            for i in issues:
                if not self._is_open(i, states):
                    continue
                for assignee_id in (i.get("assignees") or []):
                    load[assignee_id] = load.get(assignee_id, 0) + 1

        # Build name list for ranking
        id_to_name = {
            m["id"]: (
                f"{m.get('first_name','').strip()} {m.get('last_name','').strip()}".strip()
                or m.get("display_name") or m.get("email") or m["id"][:8]
            )
            for m in members if m.get("id")
        }
        ranked = sorted(
            ((id_to_name.get(uid, uid[:8]), n) for uid, n in load.items()),
            key=lambda x: -x[1],
        )

        if not ranked:
            return "Открытых задач у участников команды нет."

        idle = [
            id_to_name.get(m["id"], "?")
            for m in members if m.get("id") and m["id"] not in load
        ]
        lines = [f"Загруженность команды ({len(members)} человек)."]
        top = ranked[:5]
        lines.append(
            "Топ загруженных: "
            + "; ".join(f"{name} — {self._tasks_word(n)}" for name, n in top)
            + "."
        )
        if idle:
            tail = f"({', '.join(idle[:3])})" if len(idle) <= 3 else ""
            lines.append(
                f"Без активных задач: "
                f"{self._format_count(len(idle), 'человек', 'человека', 'человек')} "
                f"{tail}".strip() + "."
            )
        return " ".join(lines)

    # ── Scope: overdue ───────────────────────────────────────────────────

    async def _overdue(self, project_filter: str | None) -> str:
        projects = self._filter_projects(await self._list_projects(), project_filter)
        if not projects:
            return "В Plane нет проектов."
        members = await self._list_members()
        id_to_name = {
            m["id"]: m.get("display_name") or m.get("first_name") or m.get("email") or "?"
            for m in members if m.get("id")
        }

        async def fetch_one(p: dict[str, Any]) -> tuple[dict, list, dict]:
            issues, states = await asyncio.gather(
                self._project_issues(p["id"]),
                self._project_states(p["id"]),
            )
            return p, issues, states

        results = await asyncio.gather(*(fetch_one(p) for p in projects))

        today = date.today()
        overdue: list[tuple[str, str, int, list[str]]] = []  # proj_name, issue_name, days, assignee_names
        for p, issues, states in results:
            for i in issues:
                if not self._is_open(i, states):
                    continue
                td = self._parse_date(i.get("target_date"))
                if td and td < today:
                    days = (today - td).days
                    assignees = [
                        id_to_name.get(uid, "?")
                        for uid in (i.get("assignees") or [])
                    ]
                    overdue.append((p["name"], i.get("name", "?"), days, assignees))

        if not overdue:
            return "Просроченных задач нет — отлично!"

        overdue.sort(key=lambda x: -x[2])  # most-overdue first
        lines = [f"Просроченных задач: {self._tasks_word(len(overdue))}."]
        for proj, name, days, assignees in overdue[:_MAX_LIST_ITEMS]:
            assn = f" на {', '.join(assignees)}" if assignees else " без исполнителя"
            day_word = self._format_count(days, "день", "дня", "дней")
            lines.append(f"{proj}: «{name}» — просрочено на {day_word}{assn}.")
        extra = len(overdue) - _MAX_LIST_ITEMS
        if extra > 0:
            lines.append(f"И ещё {self._tasks_word(extra)}.")
        return " ".join(lines)
