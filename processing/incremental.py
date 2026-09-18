"""Conservative early-stop primitives for incremental collectors."""

from __future__ import annotations


class KnownPageStopper:
    """Stop after N consecutive non-empty pages containing only known IDs."""

    def __init__(self, known_ids=None, consecutive_pages: int = 0):
        self.known_ids = {str(x) for x in (known_ids or []) if str(x)}
        self.consecutive_pages = max(0, int(consecutive_pages or 0))
        self.streak = 0

    @property
    def enabled(self) -> bool:
        return bool(self.known_ids) and self.consecutive_pages > 0

    def observe(self, page_ids) -> bool:
        ids = {str(x) for x in (page_ids or []) if str(x)}
        if not self.enabled or not ids:
            self.streak = 0
            return False
        if ids <= self.known_ids:
            self.streak += 1
        else:
            self.streak = 0
        return self.streak >= self.consecutive_pages
