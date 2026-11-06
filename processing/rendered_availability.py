"""Opt-in browser DOM fallback for inconclusive ATS job pages.

Playwright is deliberately lazy-imported: normal collectors do not require a
browser. The full audit caps rendered pages per shard and chooses candidates
fairly across source families. Closing a vacancy requires an explicit banner
or an expired structured JobPosting validThrough date visible in page DOM.

Script load errors, blocked origins, logins and missing job descriptions
stay 'unverified'; an application button by itself is not proof of opening.
"""
from __future__ import annotations

import asyncio
from ipaddress import ip_address
from urllib.parse import urlsplit

from processing.source_availability import (
    classify_html, normalize_url, safe_url,
)


def _private_host(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in ("https", "data", "blob"):
            return True
        if parsed.scheme in ("data", "blob"):
            return False
        if host in ("localhost", "local", "metadata.google.internal"):
            return True
        if host.endswith((".localhost", ".local", ".internal")):
            return True
        try:
            address = ip_address(host)
            return not address.is_global
        except ValueError:
            return not host or "." not in host
    except ValueError:
        return True


async def _render(playwright, items, workers, timeout_ms):
    browser = await playwright.chromium.launch(
        headless=True, args=["--disable-dev-shm-usage"]
    )
    semaphore = asyncio.Semaphore(workers)
    outcomes = {}
    context = await browser.new_context(
        java_script_enabled=True,
        ignore_https_errors=False,
        service_workers="block",
    )
    try:
        async def one(item):
            source, job_id, raw_url = item
            allowed = safe_url(source, raw_url)
            if not allowed:
                return
            async with semaphore:
                page = await context.new_page()
                async def filter_route(route):
                    req = route.request
                    if _private_host(req.url) or req.resource_type in (
                        "image", "font", "media",
                    ):
                        await route.abort()
                        return
                    if (req.is_navigation_request() and req.frame == page.main_frame
                            and safe_url(source, req.url) is None):
                        await route.abort()
                        return
                    await route.continue_()
                try:
                    await page.route("**/*", filter_route)
                    await page.goto(allowed, wait_until="domcontentloaded",
                                    timeout=timeout_ms)
                    await page.wait_for_timeout(900)
                    if normalize_url(page.url) != normalize_url(allowed):
                        return
                    # Playwright inner_text() contains *visible* rendered DOM
                    # text, unlike page.content() which includes hidden modals
                    # and inactive templates with misleading closure labels.
                    from html import escape

                    visible = await page.locator("body").inner_text(timeout=4500)
                    snippets = [
                        "<p>" + escape(line.strip()) + "</p>"
                        for line in visible.splitlines()[:6000]
                        if line.strip() and len(line.strip()) <= 500
                    ]
                    verdict, evidence = classify_html(
                        source, "<main>" + "".join(snippets) + "</main>"
                    )
                    if verdict in ("open", "closed"):
                        outcomes[(source, str(job_id))] = (
                            verdict, "rendered_" + evidence
                        )
                except Exception:
                    # Browser crashes, CAPTCHAs, outages and blocks are unknown.
                    pass
                finally:
                    await page.close()
        await asyncio.gather(*(one(item) for item in items))
    finally:
        await context.close()
        await browser.close()
    return outcomes


def render_batch(items, *, workers=2, timeout_ms=14000):
    """Map (source,id) to explicit verdict; never manufacture a closed status."""
    if not items:
        return {}
    if not 1 <= workers <= 3 or not 2000 <= timeout_ms <= 30000:
        raise ValueError("Invalid rendered-audit limits")
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[RENDER] Playwright indisponivel; mantendo verificacoes inconclusivas.")
        return {}
    try:
        async def execute():
            async with async_playwright() as browser_driver:
                return await _render(browser_driver, items, workers, timeout_ms)
        return asyncio.run(execute())
    except Exception:
        # A missing Chromium installation must not change closure logic.
        print("[RENDER] Browser nao iniciou; verificacoes mantidas como inconclusivas.")
        return {}
