"""Page/limit pagination shared by list endpoints."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    limit: int

    @property
    def meta(self):
        total_pages = math.ceil(self.total / self.limit) if self.total else 0
        return {
            'total': self.total,
            'page': self.page,
            'limit': self.limit,
            'totalPages': total_pages,
            'hasNextPage': self.page < total_pages,
            'hasPreviousPage': self.page > 1,
        }


def paginate(queryset, *, page, limit):
    """Slice an already filtered and ordered queryset.

    Costs one COUNT plus one page query (plus any prefetches). A page past the
    end yields an empty list with accurate metadata rather than an error.
    """
    total = queryset.count()
    offset = (page - 1) * limit
    items = list(queryset[offset:offset + limit]) if offset < total else []
    return Page(items=items, total=total, page=page, limit=limit)
