"""Theo lenses -- pluggable analysis prompts for the code-intelligence graph.

A *lens* is a system prompt that drives a specific kind of analysis over a
repository (e.g. the ``architect`` lens builds structural Concept and SourceFile
nodes with their relationships).

    load_prompt(lens_name) -> str

Reads ``<lens_name>_prompt.md`` from this package directory and returns the raw
text.  Raises ``FileNotFoundError`` if no prompt file exists for the given lens.
"""

from __future__ import annotations

from pathlib import Path

_LENS_DIR = Path(__file__).resolve().parent


def load_prompt(lens_name: str) -> str:
    """Load a lens system prompt by name.

    Args:
        lens_name: Short identifier for the lens (e.g. ``"architect"``).

    Returns:
        The raw Markdown text of the prompt file.

    Raises:
        FileNotFoundError: If ``<lens_name>_prompt.md`` does not exist.
        ValueError: If *lens_name* contains path separators or is empty.
    """
    if not lens_name or "/" in lens_name or "\\" in lens_name:
        raise ValueError(f"Invalid lens name: {lens_name!r}")

    prompt_path = _LENS_DIR / f"{lens_name}_prompt.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"No prompt file for lens {lens_name!r}: expected {prompt_path}"
        )
    return prompt_path.read_text(encoding="utf-8")
