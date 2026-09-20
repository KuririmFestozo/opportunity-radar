import re
import unicodedata


def normalize(value: str) -> str:
    value = (value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def contains_any(text: str, terms: list[str]) -> list[str]:
    text = normalize(text)
    out = []
    for term in terms:
        n = normalize(term)
        if n and _contains_term(text, n):
            out.append(term)
    return out


def _contains_term(text: str, term: str) -> bool:
    """Match a normalized term as a complete word/phrase, never substring."""
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None
