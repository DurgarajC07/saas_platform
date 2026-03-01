"""
Pagination helpers.

PaginationParams - FastAPI query-parameter dependency
paginate()        - compute pagination metadata from a count + page/size
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fastapi import Query

from app.shared.base_schemas import PaginationMeta


@dataclass
class PaginationParams:
    """Reusable FastAPI dependency for page / page_size query params."""

    page: int = Query(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Query(default=20, ge=1, le=200, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def paginate(total_items: int, params: PaginationParams) -> PaginationMeta:
    """Build PaginationMeta from a total item count and pagination params."""
    total_pages = math.ceil(total_items / params.page_size) if total_items > 0 else 0
    return PaginationMeta(
        page=params.page,
        page_size=params.page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_previous=params.page > 1,
    )
