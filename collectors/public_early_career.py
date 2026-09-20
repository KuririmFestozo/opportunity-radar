"""Shared helpers for public Brazilian early-career listing collectors."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value) -> str:
    value = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def canonical_url(base: str, href: str) -> str:
    url = urljoin(base, clean(href))
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def stable_native_id(url: str, fallback: str = "") -> str:
    parts = urlsplit(url)
    numbers = re.findall(r"(?<!\d)(\d{4,})(?!\d)", parts.path + "?" + parts.query)
    if numbers:
        return numbers[-1]
    path = parts.path.strip("/")
    if path:
        tail = path.split("/")[-1]
        if tail and tail not in {"vagas", "vaga", "jobs", "oportunidades"}:
            return tail[:180]
    raw = normalize(f"{url}|{fallback}")
    return "h-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def nearest_card(node):
    if node is None:
        return None
    for parent in node.parents:
        if getattr(parent, "name", None) in {"article", "li"}:
            return parent
        if getattr(parent, "name", None) == "div":
            text = clean(parent.get_text(" ", strip=True))
            if 20 <= len(text) <= 3500 and parent.find(["h1", "h2", "h3", "h4", "strong"]):
                return parent
    return node.parent


def first_heading(card, fallback="") -> str:
    if card is not None:
        node = card.find(["h1", "h2", "h3", "h4"])
        if node:
            value = clean(node.get_text(" ", strip=True))
            if value:
                return value
    return clean(fallback)


def salary_from_text(value: str) -> str | None:
    match = re.search(r"R\$\s*[\d.]+(?:,\d{2})?", clean(value), re.I)
    return clean(match.group(0)) if match else None


def workplace_from_text(value: str) -> str | None:
    text = normalize(value)
    if "hibrid" in text:
        return "hybrid"
    if "home office" in text or "remot" in text:
        return "remote"
    if "presencial" in text:
        return "on-site"
    return None


def employment_from_text(value: str) -> str | None:
    text = normalize(value)
    if "jovem aprendiz" in text or "aprendiz" in text:
        return "apprentice"
    if "trainee" in text:
        return "trainee"
    if "estagio" in text or "estagiario" in text:
        return "internship"
    return None


def br_date_from_text(value: str) -> str | None:
    match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", clean(value))
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def location_from_text(value: str) -> str:
    text = clean(value)
    for pattern in (
        r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-Za-zÀ-ÿ .'-]{1,80})\s*[,/|\-]\s*([A-Z]{2})\b",
        r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-Za-zÀ-ÿ .'-]{1,80}),\s*([A-Z]{2}),\s*Brasil\b",
    ):
        matches = list(re.finditer(pattern, text))
        if matches:
            city, uf = matches[-1].group(1).strip(" -|,"), matches[-1].group(2)
            city = re.split(r"\b(?:Estágio|Trainee|Aprendiz|Presencial|Híbrido|Remoto|place)\b", city, flags=re.I)[-1].strip()
            if city:
                return f"{city}, {uf}"
    return ""


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")
