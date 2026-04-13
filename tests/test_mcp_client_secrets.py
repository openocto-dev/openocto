"""Tests for MCPSecretsStore — yaml-based bearer-token storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from openocto.mcp_client.secrets import MCPSecretsStore


@pytest.fixture()
def store(tmp_path: Path) -> MCPSecretsStore:
    return MCPSecretsStore(tmp_path / "mcp-secrets.yaml")


class TestGetHeaders:
    def test_missing_file_returns_empty(self, store: MCPSecretsStore) -> None:
        assert store.get_headers("notion") == {}

    def test_missing_server_returns_empty(self, store: MCPSecretsStore, tmp_path: Path) -> None:
        store.set_headers("github", {"Authorization": "Bearer ghp_xxx"})
        assert store.get_headers("notion") == {}


class TestSetHeaders:
    def test_set_and_get_headers(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        h = store.get_headers("notion")
        assert h == {"Authorization": "Bearer ntn_xxx"}

    def test_multiple_servers_independent(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        store.set_headers("github", {"Authorization": "Bearer ghp_yyy"})
        assert store.get_headers("notion") == {"Authorization": "Bearer ntn_xxx"}
        assert store.get_headers("github") == {"Authorization": "Bearer ghp_yyy"}

    def test_overwrite_headers(self, store: MCPSecretsStore) -> None:
        store.set_headers("svc", {"X-Old": "old"})
        store.set_headers("svc", {"X-New": "new"})
        h = store.get_headers("svc")
        assert h == {"X-New": "new"}
        assert "X-Old" not in h

    def test_multiple_headers(self, store: MCPSecretsStore) -> None:
        store.set_headers("svc", {"Authorization": "Bearer tok", "X-Custom": "val"})
        h = store.get_headers("svc")
        assert h["Authorization"] == "Bearer tok"
        assert h["X-Custom"] == "val"

    def test_chmod_600_on_create(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        path = store._path
        mode = stat.S_IMODE(os.stat(path).st_mode)
        # On macOS/Linux the file should be 0o600
        if os.name != "nt":
            assert mode == 0o600

    def test_invalid_name_raises(self, store: MCPSecretsStore) -> None:
        with pytest.raises(ValueError):
            store.set_headers("bad name!", {"Authorization": "Bearer x"})

    def test_name_starting_with_digit_raises(self, store: MCPSecretsStore) -> None:
        with pytest.raises(ValueError):
            store.set_headers("1invalid", {"Authorization": "Bearer x"})


class TestDelete:
    def test_delete_removes_entry(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        store.delete("notion")
        assert store.get_headers("notion") == {}

    def test_delete_keeps_other_entries(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        store.set_headers("github", {"Authorization": "Bearer ghp_yyy"})
        store.delete("notion")
        assert store.get_headers("github") == {"Authorization": "Bearer ghp_yyy"}
        assert store.list_names() == ["github"]

    def test_delete_missing_is_noop(self, store: MCPSecretsStore) -> None:
        # Should not raise
        store.delete("nonexistent")

    def test_delete_empty_file_noop(self, store: MCPSecretsStore) -> None:
        store.delete("any")  # file doesn't even exist yet


class TestListNames:
    def test_list_empty_initially(self, store: MCPSecretsStore) -> None:
        assert store.list_names() == []

    def test_list_after_set(self, store: MCPSecretsStore) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        store.set_headers("github", {"Authorization": "Bearer ghp_yyy"})
        names = sorted(store.list_names())
        assert names == ["github", "notion"]


class TestAtomicWrite:
    def test_file_is_valid_yaml_after_write(self, store: MCPSecretsStore, tmp_path: Path) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        with open(store._path) as fh:
            data = yaml.safe_load(fh)
        assert "servers" in data
        assert "notion" in data["servers"]

    def test_no_leftover_tmp_file(self, store: MCPSecretsStore, tmp_path: Path) -> None:
        store.set_headers("notion", {"Authorization": "Bearer ntn_xxx"})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
