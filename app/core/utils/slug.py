"""
Slug generation helpers.
"""

from slugify import slugify as _slugify


def make_slug(value: str, max_length: int = 60) -> str:
    """Convert *value* to a URL-safe slug, truncated to *max_length* chars."""
    return _slugify(value)[:max_length]


def make_unique_slug(value: str, existing_slugs: set[str], max_length: int = 60) -> str:
    """
    Return a unique slug by appending an incrementing suffix if *value*
    already exists in *existing_slugs*.
    """
    base = make_slug(value, max_length)
    candidate = base
    counter = 1
    while candidate in existing_slugs:
        suffix = f"-{counter}"
        candidate = base[: max_length - len(suffix)] + suffix
        counter += 1
    return candidate
