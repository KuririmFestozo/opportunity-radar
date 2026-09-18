import os
import random
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_HEADERS = {
    "User-Agent": (
        "OpportunityRadar/0.3.15 "
        "(personal job aggregator; low-frequency requests)"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# v3.15.2: fail-fast network policy.
#
# The old setup used one 25 s timeout and 3 retries, so a single unhealthy
# source could hold the whole collector for well over one minute. Requests'
# tuple timeout separates connection establishment from the maximum period
# without receiving bytes.
REQUEST_CONNECT_TIMEOUT = float(os.getenv("REQUEST_CONNECT_TIMEOUT", "5"))
REQUEST_READ_TIMEOUT = float(os.getenv("REQUEST_READ_TIMEOUT", "8"))
REQUEST_TOTAL_TIMEOUT = float(os.getenv("REQUEST_TOTAL_TIMEOUT", "20"))

# Kept as a public compatibility constant because some collectors import it
# directly for POST requests.
TIMEOUT = (REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT)

PUBLIC_DELAY = float(os.getenv("PUBLIC_SOURCE_DELAY_SECONDS", "0.8"))
REQUEST_RETRIES = max(1, int(os.getenv("REQUEST_RETRIES", "2")))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "0.8"))

# Reaproveita conexões TCP entre chamadas do mesmo processo.
_SESSION = requests.Session()


def _read_response_with_deadline(
    response: requests.Response,
    total_timeout: float = REQUEST_TOTAL_TIMEOUT,
) -> requests.Response:
    """Fully buffer a streamed response while enforcing a wall-clock deadline.

    ``requests`` does not provide a true total-transfer timeout. Its read
    timeout only limits how long a socket may stay silent. A server that keeps
    trickling bytes could therefore block a collector indefinitely. We stream
    the body ourselves and stop once the total transfer deadline is exceeded.
    """
    deadline = time.monotonic() + max(1.0, float(total_timeout))
    chunks: list[bytes] = []

    for chunk in response.iter_content(chunk_size=64 * 1024):
        if time.monotonic() > deadline:
            raise requests.Timeout(
                f"tempo total de resposta excedeu {total_timeout:.1f}s"
            )
        if chunk:
            chunks.append(chunk)

    # ``Response.json()`` and ``Response.text`` continue working normally.
    response._content = b"".join(chunks)
    response._content_consumed = True
    return response


def _request(url: str, params=None, headers=None, polite_delay=False):
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)

    if polite_delay:
        time.sleep(PUBLIC_DELAY)

    last_error = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        response = None
        try:
            response = _SESSION.get(
                url,
                params=params,
                headers=merged,
                timeout=TIMEOUT,
                stream=True,
            )

            # Erros transitórios de servidor/rate-limit também merecem retry.
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                if attempt < REQUEST_RETRIES:
                    wait = (
                        RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                        + random.uniform(0, 0.25)
                    )
                    time.sleep(wait)
                    continue

            response.raise_for_status()
            return _read_response_with_deadline(response)

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if response is not None:
                response.close()

            if attempt >= REQUEST_RETRIES:
                raise

            wait = (
                RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                + random.uniform(0, 0.25)
            )
            time.sleep(wait)

        except Exception:
            if response is not None:
                response.close()
            raise

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
