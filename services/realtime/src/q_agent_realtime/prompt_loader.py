from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

_INCLUDE_RE = re.compile(r"\{\{\s*include:([a-zA-Z0-9_\-]+)\s*\}\}")
_VAR_RE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")


def _default_prompt_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def prompt_dir() -> Path:
    override = os.getenv("Q_AGENT_PROMPT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _default_prompt_dir()


@lru_cache(maxsize=32)
def _read_raw(name: str, directory: str) -> str:
    path = Path(directory) / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def clear_prompt_cache() -> None:
    _read_raw.cache_clear()


def load_prompt(name: str, **variables: object) -> str:
    """Load a markdown system prompt and substitute {{VAR}} placeholders.

    Optional includes: ``{{include:shared_name}}`` without the ``.md`` suffix.
    Shared files conventionally start with ``_`` (e.g. ``_shared``).
    """
    directory = str(prompt_dir())
    text = _read_raw(name, directory)

    def _include(match: re.Match[str]) -> str:
        included = match.group(1)
        # Allow both "_shared" and "shared" → prefer exact, then _prefix.
        try:
            return _read_raw(included, directory)
        except FileNotFoundError:
            return _read_raw(f"_{included}", directory)

    # Resolve includes once (no nested include expansion for simplicity).
    text = _INCLUDE_RE.sub(_include, text)

    string_vars = {key: str(value) for key, value in variables.items()}

    def _replace_var(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in string_vars:
            return match.group(0)
        return string_vars[key]

    return _VAR_RE.sub(_replace_var, text).strip()
