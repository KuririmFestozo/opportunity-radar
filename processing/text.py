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
        if n and n in text:
            out.append(term)
    return out
