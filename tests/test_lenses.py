"""Tests for theo.lenses -- prompt loading and content validation."""

from __future__ import annotations

import pytest

from theo.lenses import load_prompt


class TestLoadPrompt:
    """Test the load_prompt function."""

    def test_load_architect_prompt(self) -> None:
        text = load_prompt("architect")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_load_nonexistent_lens_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="no-such-lens"):
            load_prompt("no-such-lens")

    def test_empty_lens_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid lens name"):
            load_prompt("")

    def test_path_traversal_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid lens name"):
            load_prompt("../etc/passwd")

    def test_backslash_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid lens name"):
            load_prompt("foo\\bar")


class TestArchitectPromptContent:
    """Validate the architect prompt has the expected sections."""

    @pytest.fixture()
    def prompt(self) -> str:
        return load_prompt("architect")

    def test_has_core_philosophy(self, prompt: str) -> None:
        assert "## Core Philosophy" in prompt

    def test_has_schema(self, prompt: str) -> None:
        assert "## Schema" in prompt

    def test_has_cow_workflow(self, prompt: str) -> None:
        assert "## Copy-on-Write (COW) Workflow" in prompt

    def test_has_kind_definitions(self, prompt: str) -> None:
        assert "## Kind Definitions" in prompt

    def test_has_git_revision_tagging(self, prompt: str) -> None:
        assert "## `git_revision` Tagging" in prompt

    def test_has_indexing_protocol(self, prompt: str) -> None:
        assert "## Indexing Protocol" in prompt

    def test_has_quality_bar(self, prompt: str) -> None:
        assert "## Quality Bar" in prompt

    def test_has_incremental_reindexing(self, prompt: str) -> None:
        assert "## Incremental Re-indexing" in prompt

    def test_has_tools_section(self, prompt: str) -> None:
        assert "## Tools" in prompt

    def test_has_rules_section(self, prompt: str) -> None:
        assert "## Rules" in prompt

    def test_kind_root_defined(self, prompt: str) -> None:
        assert "**`root`**" in prompt

    def test_kind_system_defined(self, prompt: str) -> None:
        assert "**`system`**" in prompt

    def test_kind_subsystem_defined(self, prompt: str) -> None:
        assert "**`subsystem`**" in prompt

    def test_kind_module_defined(self, prompt: str) -> None:
        assert "**`module`**" in prompt

    def test_no_vito_references(self, prompt: str) -> None:
        assert "/root/vito/" not in prompt
        assert "/root/vito-data/" not in prompt

    def test_no_symbol_table(self, prompt: str) -> None:
        # No Symbol node table in Theo's Phase 1
        assert "Symbol" not in prompt

    def test_no_defined_in(self, prompt: str) -> None:
        assert "DefinedIn" not in prompt

    def test_no_cardea_references(self, prompt: str) -> None:
        assert "Cardea" not in prompt
        assert "cardea" not in prompt

    def test_tool_paths_use_python_m(self, prompt: str) -> None:
        assert "python -m theo.tools." in prompt

    def test_git_revision_in_schema(self, prompt: str) -> None:
        assert "git_revision" in prompt

    def test_embedding_is_invisible_to_model(self, prompt: str) -> None:
        # Embedding computation is internal to the tools -- the prompt should
        # NOT mention implementation details like theo._embed or embed_text.
        assert "theo._embed" not in prompt
        assert "embed_text" not in prompt
        assert "Automatic embeddings" not in prompt

    def test_repository_agnostic_heuristics(self, prompt: str) -> None:
        assert "## Repository-Agnostic Heuristics" in prompt

    def test_structural_validation_uses_correct_kinds(self, prompt: str) -> None:
        # Validation queries should reference 'root' not 'system' as the hierarchy root
        assert "kind: 'root'" in prompt or "kind <> 'root'" in prompt

    def test_read_only_rule(self, prompt: str) -> None:
        assert "READ-ONLY" in prompt
