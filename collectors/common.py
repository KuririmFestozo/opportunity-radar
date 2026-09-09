import os
import random
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_HEADERS = {
    "User-Agent": (
        "OpportunityRadar/0.3.4 "
        "(personal job aggregator; low-frequency requests)"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))
PUBLIC_DELAY = float(os.getenv("PUBLIC_SOURCE_DELAY_SECONDS", "0.8"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "1.0"))

# Reaproveita conexões TCP entre chamadas do mesmo processo.
_SESSION = requests.Session()


def _request(url: str, params=None, headers=None, polite_delay=False):
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)

    if polite_delay:
        time.sleep(PUBLIC_DELAY)

    last_error = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = _SESSION.get(
                url,
                params=params,
                headers=merged,
                timeout=TIMEOUT,
            )

            # Erros transitórios de servidor/rate-limit também merecem retry.
            if response.status_code in {429, 500, 502, 503, 504} and attempt < REQUEST_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.35)
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt >= REQUEST_RETRIES:
                raise

            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.35)
            time.sleep(wait)

    if last_error:
        raise last_error
    raise RuntimeError(f"Falha inesperada ao acessar {url}")


def get_json(url: str, params: dict | None = None, headers: dict | None = None):
    return _request(url, params=params, headers=headers).json()


def get_text(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    polite_delay: bool = True,
) -> str:
    return _request(
        url,
        params=params,
        headers=headers,
        polite_delay=polite_delay,
    ).text


def absolute_base(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"
