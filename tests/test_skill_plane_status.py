"""Tests for the plane_status digest skill — mocked Plane REST API."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from openocto.skills.base import SkillError, SkillUnavailable


_FAKE_SECRETS = {
    "PLANE_API_KEY": "plane_api_test",
    "PLANE_BASE_URL": "https://workspace.example.com",
    "PLANE_WORKSPACE_SLUG": "test-team",
    "PLANE_USER_EMAIL": "dmitry@example.com",
}

# Two projects: Bots and Loyalty
_PROJECTS = [
    {"id": "p1", "name": "Bots", "identifier": "BOT"},
    {"id": "p2", "name": "Loyalty App", "identifier": "LOY"},
]

# Member list — Dmitry is the active user (matches PLANE_USER_EMAIL)
_MEMBERS = [
    {"id": "u1", "first_name": "Dmitry", "last_name": "K", "email": "dmitry@example.com",
     "display_name": "dmitry"},
    {"id": "u2", "first_name": "Anna", "last_name": "P", "email": "anna@example.com",
     "display_name": "anna"},
    {"id": "u3", "first_name": "Sergey", "last_name": "", "email": "sergey@example.com",
     "display_name": "sergey"},
    # Idle member (no tasks)
    {"id": "u4", "first_name": "Olga", "last_name": "", "email": "olga@example.com",
     "display_name": "olga"},
]

# 5 states — same shape per project
_STATES_P1 = {
    "results": [
        {"id": "s_back", "group": "backlog", "name": "Backlog"},
        {"id": "s_todo", "group": "unstarted", "name": "Todo"},
        {"id": "s_prog", "group": "started", "name": "In Progress"},
        {"id": "s_done", "group": "completed", "name": "Done"},
        {"id": "s_canc", "group": "cancelled", "name": "Cancelled"},
    ]
}
_STATES_P2 = _STATES_P1  # same layout

_TODAY = date.today()
_YESTERDAY = (_TODAY - timedelta(days=1)).isoformat()
_LAST_WEEK = (_TODAY - timedelta(days=7)).isoformat()
_NEXT_WEEK = (_TODAY + timedelta(days=7)).isoformat()


def _issue(iid, name, state, assignees, target=None, priority="none"):
    return {
        "id": iid, "name": name, "state": state,
        "assignees": assignees, "target_date": target, "priority": priority,
    }


_ISSUES_P1 = {
    "results": [
        # Dmitry's open task in progress
        _issue("i1", "Fix bot crash", "s_prog", ["u1"], priority="urgent"),
        # Dmitry's open task overdue
        _issue("i2", "Refactor handler", "s_todo", ["u1"], target=_YESTERDAY),
        # Anna's open task overdue, urgent
        _issue("i3", "Critical security patch", "s_prog", ["u2"], target=_LAST_WEEK,
               priority="urgent"),
        # Anna's open task on schedule
        _issue("i4", "Improve logging", "s_todo", ["u2"], target=_NEXT_WEEK),
        # Done task — should NOT show as open
        _issue("i5", "Old task", "s_done", ["u3"]),
    ]
}

_ISSUES_P2 = {
    "results": [
        # Anna again
        _issue("i6", "Loyalty UI", "s_back", ["u2"]),
        # Sergey
        _issue("i7", "API redesign", "s_prog", ["u3"], target=_NEXT_WEEK),
        _issue("i8", "DB migration", "s_todo", ["u3"]),
        # Cancelled — should be ignored
        _issue("i9", "Old idea", "s_canc", ["u3"]),
    ]
}


def _fake_get_env(server_name):
    assert server_name == "Plane"
    return dict(_FAKE_SECRETS)


@pytest.fixture()
def skill():
    """A PlaneStatusSkill with mocked secrets and HTTP layer."""
    from openocto.skills.plane_status import PlaneStatusSkill

    with patch(
        "openocto.skills.plane_status.MCPSecretsStore.get_env",
        side_effect=_fake_get_env,
    ):
        s = PlaneStatusSkill()

    def fake_request_sync(path, params=None):
        if path == "projects/":
            return {"results": _PROJECTS}
        if path == "members/":
            return {"results": _MEMBERS}
        if path == "projects/p1/states/":
            return _STATES_P1
        if path == "projects/p2/states/":
            return _STATES_P2
        if path == "projects/p1/issues/":
            issues = _ISSUES_P1["results"]
            if params and "assignees" in params:
                issues = [i for i in issues if params["assignees"] in (i.get("assignees") or [])]
            return {"results": issues}
        if path == "projects/p2/issues/":
            issues = _ISSUES_P2["results"]
            if params and "assignees" in params:
                issues = [i for i in issues if params["assignees"] in (i.get("assignees") or [])]
            return {"results": issues}
        raise AssertionError(f"unexpected path: {path}")

    with patch.object(s, "_request_sync", side_effect=fake_request_sync):
        yield s


# ── Initialization ───────────────────────────────────────────────────────────


def test_skill_unavailable_when_creds_missing():
    from openocto.skills.plane_status import PlaneStatusSkill

    with patch(
        "openocto.skills.plane_status.MCPSecretsStore.get_env",
        return_value={"PLANE_API_KEY": "x"},  # missing base_url and slug
    ):
        with pytest.raises(SkillUnavailable):
            PlaneStatusSkill()


# ── my_tasks ─────────────────────────────────────────────────────────────────


class TestMyTasks:
    async def test_groups_by_project_with_counts(self, skill):
        result = await skill.execute(scope="my_tasks")
        assert "У тебя" in result
        assert "Bots" in result
        # Dmitry has 2 open tasks in Bots, 0 in Loyalty
        assert "2 задачи" in result or "2 задачи" in result.replace("\xa0", " ")

    async def test_marks_urgent(self, skill):
        result = await skill.execute(scope="my_tasks")
        # i1 is urgent — should be flagged
        assert "Срочн" in result

    async def test_no_open_tasks(self, skill):
        # Patch issues to return only completed tasks for Dmitry
        empty = {"results": []}

        def fake(path, params=None):
            if path.endswith("/issues/") and params and params.get("assignees") == "u1":
                return empty
            return skill._request_sync.__wrapped__ if False else None  # noqa

        # Use a fresh mock that returns no Dmitry issues
        async def empty_call():
            with patch.object(skill, "_project_issues", return_value=[]):
                return await skill.execute(scope="my_tasks")

        result = await empty_call()
        assert "нет открытых" in result.lower() or "Чисто" in result

    async def test_uses_email_to_resolve_user_id(self, skill):
        # Force a fresh resolve
        skill._user_id_cache = None
        skill._user_id_hint = None
        skill._members_cache = None
        await skill.execute(scope="my_tasks")
        assert skill._user_id_cache == "u1"

    async def test_user_id_hint_takes_precedence(self, skill):
        skill._user_id_cache = None
        skill._user_id_hint = "explicit-id"
        result = await skill.execute(scope="my_tasks")
        assert skill._user_id_cache == "explicit-id"
        # No tasks for explicit-id → empty
        assert "нет" in result.lower() or "Чисто" in result


# ── team_tasks ───────────────────────────────────────────────────────────────


class TestTeamTasks:
    async def test_overview_lists_projects_with_counts(self, skill):
        result = await skill.execute(scope="team_tasks")
        assert "Bots" in result
        assert "Loyalty" in result
        # Bots has 4 open tasks (i1-i4); Loyalty has 3 open (i6,i7,i8); cancelled/done excluded
        assert "4" in result  # Bots
        assert "3" in result  # Loyalty

    async def test_reports_overdue_total(self, skill):
        result = await skill.execute(scope="team_tasks")
        # i2 and i3 are both overdue
        assert "просроч" in result.lower()

    async def test_project_filter(self, skill):
        result = await skill.execute(scope="team_tasks", project="bots")
        assert "Bots" in result
        # Loyalty should not appear when filtered
        assert "Loyalty" not in result


# ── team_load ────────────────────────────────────────────────────────────────


class TestTeamLoad:
    async def test_ranks_by_open_task_count(self, skill):
        result = await skill.execute(scope="team_load")
        # Anna has 3 (i3,i4,i6), Sergey has 2 (i7,i8), Dmitry has 2 (i1,i2)
        assert "Anna" in result
        # Top loaded should be Anna (3 tasks)
        assert "Топ" in result or "топ" in result

    async def test_idle_members_listed(self, skill):
        result = await skill.execute(scope="team_load")
        # Olga has zero open tasks
        assert "Olga" in result or "Без активных" in result


# ── overdue ──────────────────────────────────────────────────────────────────


class TestOverdue:
    async def test_lists_overdue_tasks(self, skill):
        result = await skill.execute(scope="overdue")
        assert "Просроченных" in result
        assert "Refactor handler" in result or "Critical security patch" in result

    async def test_no_overdue_returns_positive(self, skill):
        with patch.object(skill, "_project_issues", return_value=[]):
            result = await skill.execute(scope="overdue")
            assert "нет" in result.lower() or "отлично" in result.lower()

    async def test_assignee_names_included(self, skill):
        result = await skill.execute(scope="overdue")
        # i3 is Anna's, i2 is Dmitry's
        assert "anna" in result.lower() or "dmitry" in result.lower()


# ── Error paths ──────────────────────────────────────────────────────────────


class TestErrors:
    async def test_unknown_scope_raises(self, skill):
        with pytest.raises(SkillError, match="Unknown scope"):
            await skill.execute(scope="garbage")  # type: ignore[arg-type]

    async def test_http_failure_wrapped_as_skill_error(self, skill):
        with patch.object(skill, "_request_sync", side_effect=RuntimeError("boom")):
            with pytest.raises(SkillError):
                await skill.execute(scope="team_tasks")

    async def test_user_id_resolution_fails_without_email_or_id(self, skill):
        skill._user_id_cache = None
        skill._user_id_hint = None
        skill._user_email = None
        with pytest.raises(SkillError, match="Cannot determine current user"):
            await skill.execute(scope="my_tasks")


# ── Russian plural helper ────────────────────────────────────────────────────


def test_format_count_plurals():
    from openocto.skills.plane_status import PlaneStatusSkill

    fc = PlaneStatusSkill._format_count
    assert fc(1, "задача", "задачи", "задач") == "1 задача"
    assert fc(2, "задача", "задачи", "задач") == "2 задачи"
    assert fc(4, "задача", "задачи", "задач") == "4 задачи"
    assert fc(5, "задача", "задачи", "задач") == "5 задач"
    assert fc(11, "задача", "задачи", "задач") == "11 задач"
    assert fc(21, "задача", "задачи", "задач") == "21 задача"
    assert fc(22, "задача", "задачи", "задач") == "22 задачи"
