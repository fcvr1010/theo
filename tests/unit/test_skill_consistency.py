"""Guard against drift between the three SKILL.md copies.

Theo ships its agent skill instructions in three places:

* ``.agents/skills/theo/SKILL.md`` — for projects checked out under the
  ``.agents/`` convention.
* ``.claude/skills/theo/SKILL.md`` — for Claude Code's ``.claude/skills``
  layout.
* ``src/theo/skills/theo/SKILL.md`` — bundled inside the Python package, so
  ``pip install theo`` users get a copy without the surrounding repo.

All three must stay byte-for-byte identical.  In review of PR #33 the
``src/`` copy had silently drifted — missing the "no embedded newlines in
notes" rule that prevents ``theo_reload`` from failing on multi-line
descriptions.  This test fails loudly on any future drift so we don't ship
an inconsistent ruleset to end users.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SKILL_PATHS = (
    REPO_ROOT / ".agents" / "skills" / "theo" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "theo" / "SKILL.md",
    REPO_ROOT / "src" / "theo" / "skills" / "theo" / "SKILL.md",
)


def test_all_skill_copies_are_byte_identical() -> None:
    """The three SKILL.md copies must be byte-for-byte identical."""
    contents = {p: p.read_bytes() for p in SKILL_PATHS}
    # Cheap, deterministic baseline: pick the first path and compare every
    # other to it. If any two differ, surface both paths in the assertion
    # message so the failure is actionable without needing to re-run a diff.
    baseline_path, baseline_bytes = next(iter(contents.items()))
    for path, data in contents.items():
        assert data == baseline_bytes, (
            f"SKILL.md drift detected: {path} differs from {baseline_path}. "
            "Run `diff` between the three copies and re-sync."
        )
