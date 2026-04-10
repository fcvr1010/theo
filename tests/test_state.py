"""Tests for theo.state."""

from __future__ import annotations

import json
from pathlib import Path

from theo.config import TheoConfig
from theo.state import TheoState, load_state, save_state


class TestTheoState:
    """Test state serialisation and persistence."""

    def _make_config(self, tmp_path: Path) -> TheoConfig:
        config = TheoConfig(project_dir=tmp_path)
        config.ensure_dirs()
        return config

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        config = self._make_config(tmp_path)
        state = TheoState(
            project="my-project",
            last_indexed_commit="abc123",
            last_indexed_at="2026-01-15T10:30:00Z",
        )
        save_state(config, state)
        loaded = load_state(config)
        assert loaded.project == "my-project"
        assert loaded.last_indexed_commit == "abc123"
        assert loaded.last_indexed_at == "2026-01-15T10:30:00Z"

    def test_save_and_load_null_fields(self, tmp_path: Path) -> None:
        config = self._make_config(tmp_path)
        state = TheoState(project="fresh")
        save_state(config, state)
        loaded = load_state(config)
        assert loaded.project == "fresh"
        assert loaded.last_indexed_commit is None
        assert loaded.last_indexed_at is None

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        import pytest

        config = self._make_config(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_state(config)

    def test_atomic_write_creates_valid_json(self, tmp_path: Path) -> None:
        config = self._make_config(tmp_path)
        state = TheoState(project="atomic-test")
        save_state(config, state)
        raw = config.state_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["project"] == "atomic-test"

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        config = self._make_config(tmp_path)
        save_state(config, TheoState(project="v1"))
        save_state(config, TheoState(project="v2", last_indexed_commit="def456"))
        loaded = load_state(config)
        assert loaded.project == "v2"
        assert loaded.last_indexed_commit == "def456"

    def test_no_temp_files_left_on_success(self, tmp_path: Path) -> None:
        config = self._make_config(tmp_path)
        save_state(config, TheoState(project="clean"))
        # Only state.json and logs/ should be in .theo/
        theo_contents = list(config.theo_dir.iterdir())
        names = {p.name for p in theo_contents}
        assert ".state-" not in "".join(names), "Temp file was not cleaned up"
