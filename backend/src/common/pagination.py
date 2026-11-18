from src.core.errors import ApiError


class Pagination:
    def __init__(self, page: int = 1, page_size: int = 20) -> None:
        self.page = max(1, page)
        self.page_size = min(100, max(1, page_size))

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_payload(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "page": page, "page_size": page_size, "total": total}


__all__ = ["Pagination", "page_payload", "ApiError"]
