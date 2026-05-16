from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from .rag import normalize_scheme


class ScrapeError(RuntimeError):
    pass


@dataclass
class PortalConfig:
    name: str
    url: str
    card_selector: str
    name_selector: str
    description_selector: str
    apply_selector: str = "a"
    state: str = "All"
    gender: str = "All"
    category: str = "General,OBC,SC,ST"
    age_min: int = 0
    age_max: int = 120
    income_limit_inr: int = 9999999
    language: str = "en"

    def validate(self) -> None:
        if "example." in self.url or self.url.startswith("https://example"):
            raise ScrapeError(
                f"{self.name} uses placeholder URL {self.url}. "
                "Replace portals.example.json with a real government portal URL and selectors."
            )
        required = {
            "card_selector": self.card_selector,
            "name_selector": self.name_selector,
            "description_selector": self.description_selector,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ScrapeError(f"{self.name} is missing required selectors: {', '.join(missing)}")


async def scrape_portal(config: PortalConfig, limit: int | None = None) -> list[dict[str, Any]]:
    """Scrape a scheme listing page with Playwright and normalize extracted cards.

    Different government portals expose different HTML, so this accepts selectors
    instead of hard-coding one site. The normalized output can be upserted into
    PostgreSQL with embeddings by `sarathi.ingest`.
    """
    try:
        from bs4 import BeautifulSoup
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ScrapeError(
            "Portal scraping needs Playwright and BeautifulSoup. "
            "Install them with: pip install -r requirements.txt && playwright install chromium"
        ) from exc

    config.validate()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(config.url, wait_until="networkidle", timeout=60000)
            html = await page.content()
        except Exception as exc:
            raise ScrapeError(f"Could not open {config.name} at {config.url}: {exc}") from exc
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(config.card_selector)
    if limit:
        cards = cards[:limit]

    schemes: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        name_el = card.select_one(config.name_selector)
        desc_el = card.select_one(config.description_selector)
        link_el = card.select_one(config.apply_selector)
        if not name_el or not desc_el:
            continue
        href = link_el.get("href") if link_el else config.url
        if href and href.startswith("/"):
            href = config.url.rstrip("/") + href
        schemes.append(
            normalize_scheme(
                {
                    "id": f"{config.name.upper().replace(' ', '-')}-{index}",
                    "name": name_el.get_text(" ", strip=True),
                    "description": desc_el.get_text(" ", strip=True),
                    "state": config.state,
                    "gender": config.gender,
                    "category": config.category,
                    "age_min": config.age_min,
                    "age_max": config.age_max,
                    "income_limit_inr": config.income_limit_inr,
                    "apply_url": href or config.url,
                    "source_url": config.url,
                    "source_portal": config.name,
                    "language": config.language,
                }
            )
        )
    return schemes


def scrape_portal_sync(config: PortalConfig, limit: int | None = None) -> list[dict[str, Any]]:
    return asyncio.run(scrape_portal(config, limit=limit))


async def scrape_india_gov_schemes(
    url: str = "https://www.india.gov.in/my-government/schemes",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Scrape scheme links from the National Portal of India's schemes page.

    The public page currently exposes reliable scheme records in its Featured
    Schemes section. Category/ministry search pages are linked from the same page
    but may return no server-rendered records, so this scraper intentionally
    captures concrete scheme links rather than empty category pages.
    """
    try:
        from bs4 import BeautifulSoup
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ScrapeError(
            "India.gov.in scraping needs Playwright and BeautifulSoup. "
            "Install them with: pip install -r requirements.txt && playwright install chromium"
        ) from exc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        )
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            html = await page.content()
        except Exception as exc:
            raise ScrapeError(f"Could not open India.gov.in schemes page at {url}: {exc}") from exc
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True).lower()
    if "access denied" in page_text and "permission to access" in page_text:
        raise ScrapeError("India.gov.in blocked the scraper with an Access Denied response.")

    featured_heading = soup.find(
        lambda tag: tag.name in {"h2", "h3"} and "featured schemes" in tag.get_text(" ", strip=True).lower()
    )
    if not featured_heading:
        raise ScrapeError("Could not find the Featured Schemes section on India.gov.in.")

    links = []
    for sibling in featured_heading.find_all_next():
        if sibling.name in {"h1", "h2"} and sibling is not featured_heading:
            break
        if sibling.name == "a" and sibling.get_text(" ", strip=True):
            links.append(sibling)
        links.extend(sibling.select("a[href]") if hasattr(sibling, "select") else [])

    seen: set[str] = set()
    schemes: list[dict[str, Any]] = []
    for link in links:
        title = link.get_text(" ", strip=True)
        href = urljoin(url, link.get("href", ""))
        if not title or not href or href in seen:
            continue
        seen.add(href)
        digest = hashlib.sha1(href.encode("utf-8")).hexdigest()[:10].upper()
        schemes.append(
            normalize_scheme(
                {
                    "id": f"INDIA-GOV-{digest}",
                    "name": title,
                    "description": (
                        f"Featured scheme or citizen service listed on the National Portal of India. "
                        f"Open the official link for full eligibility, benefits, and application details."
                    ),
                    "state": "All",
                    "gender": "All",
                    "category": ["General", "OBC", "SC", "ST", "Minority"],
                    "age_min": 0,
                    "age_max": 120,
                    "income_limit_inr": 9999999,
                    "apply_url": href,
                    "source_url": url,
                    "source_portal": "National Portal of India",
                    "language": "en",
                }
            )
        )
        if limit and len(schemes) >= limit:
            break

    if not schemes:
        raise ScrapeError("No featured scheme links were extracted from India.gov.in.")
    return schemes


def scrape_india_gov_schemes_sync(
    url: str = "https://www.india.gov.in/my-government/schemes",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return asyncio.run(scrape_india_gov_schemes(url=url, limit=limit))

MYSHEME_URLS = [
    "https://www.myscheme.gov.in/search/ministry/Ministry%20Of%20Micro,%20Small%20and%20Medium%20Enterprises",
    "https://www.myscheme.gov.in/search/ministry/Ministry%20Of%20Agriculture%20and%20Farmers%20Welfare",
    "https://www.myscheme.gov.in/search/ministry/Ministry%20of%20Education",
    "https://www.myscheme.gov.in/search/ministry/Ministry%20Of%20Health%20%26%20Family%20Welfare",
    "https://www.myscheme.gov.in/search/ministry/Ministry%20Of%20Home%20Affairs",
]



async def scrape_myscheme_pages(
    urls: list[str] | None = None,
    limit: int | None = None,
    max_scrolls: int = 12,
) -> list[dict[str, Any]]:
    """Scrape scheme cards from myScheme rendered search pages.

    myScheme is a JavaScript app, so this uses Playwright, waits for rendering,
    scrolls lazy-loaded results, then extracts visible links that point to scheme
    detail pages. It intentionally ignores navigation/footer links.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ScrapeError(
            "myScheme scraping needs Playwright. Install it with: "
            "pip install -r requirements.txt && playwright install chromium"
        ) from exc

    target_urls = urls or MYSHEME_URLS
    schemes_by_url: dict[str, dict[str, Any]] = {}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        )

        for source_url in target_urls:
            try:
                await page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                previous_height = 0
                for _ in range(max_scrolls):
                    height = await page.evaluate("document.body.scrollHeight")
                    if height == previous_height:
                        break
                    previous_height = height
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1200)

                cards = await page.evaluate(
                    """
                    () => {
                      const schemeHref = (href) => {
                        if (!href) return false;
                        try {
                          const url = new URL(href, location.origin);
                          return url.hostname.endsWith('myscheme.gov.in') &&
                            /\\/schemes?\\//i.test(url.pathname);
                        } catch {
                          return false;
                        }
                      };

                      const anchors = Array.from(document.querySelectorAll('a[href]'))
                        .filter((a) => schemeHref(a.href));

                      return anchors.map((a) => {
                        const card = a.closest('article, li, .card, [class*="card"], [class*="scheme"], [class*="Scheme"]') || a.parentElement;
                        const rawText = (card?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim();
                        const title = (a.innerText || '').replace(/\\s+/g, ' ').trim() ||
                          rawText.split(/[.|\\n]/)[0];
                        return { title, href: a.href, text: rawText };
                      }).filter((item) => item.title && item.href);
                    }
                    """
                )
            except Exception as exc:
                await browser.close()
                raise ScrapeError(f"Could not scrape myScheme page {source_url}: {exc}") from exc

            for card in cards:
                href = card["href"]
                if href in schemes_by_url:
                    continue
                title = card["title"].strip()
                body = card["text"].strip()
                description = body.replace(title, "", 1).strip(" -|")
                if not description:
                    description = (
                        "Scheme listed on myScheme. Open the official detail page for "
                        "eligibility, benefits, documents, and application steps."
                    )
                digest = hashlib.sha1(href.encode("utf-8")).hexdigest()[:10].upper()
                scope = "Central" if "/ministry/" in source_url else "State/UT"
                schemes_by_url[href] = normalize_scheme(
                    {
                        "id": f"MYSCHEME-{digest}",
                        "name": title,
                        "description": description,
                        "state": "All",
                        "gender": "All",
                        "category": ["General", "OBC", "SC", "ST", "Minority"],
                        "age_min": 0,
                        "age_max": 120,
                        "income_limit_inr": 9999999,
                        "apply_url": href,
                        "source_url": source_url,
                        "source_portal": f"myScheme {scope}",
                        "language": "en",
                    }
                )
                if limit and len(schemes_by_url) >= limit:
                    await browser.close()
                    return list(schemes_by_url.values())

        await browser.close()

    if not schemes_by_url:
        raise ScrapeError(
            "No scheme links were extracted from myScheme. The pages may be returning "
            "'No data found', blocking automation, or using an API that needs additional access."
        )
    return list(schemes_by_url.values())


def scrape_myscheme_pages_sync(limit: int | None = None, max_scrolls: int = 12) -> list[dict[str, Any]]:
    return asyncio.run(scrape_myscheme_pages(limit=limit, max_scrolls=max_scrolls))
