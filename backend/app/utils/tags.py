from __future__ import annotations

import re

_TAG_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class TagValidationError(ValueError):
    pass


def normalize_tags(tags: list[str] | None, max_tags: int = 10) -> list[str]:
    """Trim, collapse whitespace, lowercase and de-duplicate tags."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        if not isinstance(raw, str):
            raise TagValidationError("tags must be strings")
        tag = _TAG_WHITESPACE.sub(" ", raw.strip()).lower()
        if not tag:
            continue
        if len(tag) > 32:
            raise TagValidationError("each tag must be 32 characters or fewer")
        if _CONTROL.search(tag):
            raise TagValidationError("tags may not contain control characters")
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    if len(result) > max_tags:
        raise TagValidationError(f"at most {max_tags} tags are allowed")
    return result
