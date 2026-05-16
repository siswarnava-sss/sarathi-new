from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .rag import BGEEmbedder, SchemeStore, load_json_schemes, normalize_scheme
from .scraper import (
    PortalConfig,
    ScrapeError,
    scrape_india_gov_schemes_sync,
    scrape_myscheme_pages_sync,
    scrape_portal_sync,
)


def require_database(store: SchemeStore) -> None:
    if not store.enabled:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set DATABASE_URL before ingesting into PostgreSQL/pgvector. "
            "The Streamlit app can still run with schemes.json fallback."
        )


def upsert_with_progress(store: SchemeStore, schemes: list[dict], embedder: BGEEmbedder | None) -> None:
    if embedder:
        print("Generating BGE embeddings. First run can take several minutes while the model downloads/loads...", flush=True)
    else:
        print("Skipping embeddings. Rows will be inserted with empty vector values.", flush=True)
    print("Writing schemes to PostgreSQL...", flush=True)
    store.upsert_many(schemes, embedder)
    print("Database write complete.", flush=True)


def make_embedder(skip_embeddings: bool) -> BGEEmbedder | None:
    return None if skip_embeddings else BGEEmbedder()


def ingest_json(path: str, skip_embeddings: bool = False) -> int:
    schemes = load_json_schemes(path)
    store = SchemeStore()
    require_database(store)
    upsert_with_progress(store, schemes, make_embedder(skip_embeddings))
    return len(schemes)


def ingest_portals(config_path: str, limit: int | None = None, skip_embeddings: bool = False) -> int:
    configs = json.loads(Path(config_path).read_text(encoding="utf-8"))
    store = SchemeStore()
    require_database(store)
    embedder = make_embedder(skip_embeddings)
    total = 0
    for item in configs:
        config = PortalConfig(**item)
        print(f"Scraping {config.name}: {config.url}")
        schemes = [normalize_scheme(scheme) for scheme in scrape_portal_sync(config, limit=limit)]
        print(f"Extracted {len(schemes)} schemes from {config.name}.")
        upsert_with_progress(store, schemes, embedder)
        total += len(schemes)
    return total


def ingest_india_gov(limit: int | None = None, skip_embeddings: bool = False) -> int:
    store = SchemeStore()
    require_database(store)
    embedder = make_embedder(skip_embeddings)
    schemes = scrape_india_gov_schemes_sync(limit=limit)
    print(f"Extracted {len(schemes)} schemes from India.gov.in.")
    upsert_with_progress(store, schemes, embedder)
    return len(schemes)


def ingest_myscheme(limit: int | None = None, skip_embeddings: bool = False) -> int:
    store = SchemeStore()
    require_database(store)
    embedder = make_embedder(skip_embeddings)
    schemes = scrape_myscheme_pages_sync(limit=limit)
    print(f"Extracted {len(schemes)} schemes from myScheme ministry/state pages.")
    upsert_with_progress(store, schemes, embedder)
    return len(schemes)


def count_database() -> int:
    store = SchemeStore()
    require_database(store)
    return store.count_schemes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape, normalize, embed, and upsert government schemes.")
    parser.add_argument("--json", help="Load seed schemes from a JSON file.")
    parser.add_argument("--portals", help="Load Playwright portal selector configs from JSON.")
    parser.add_argument(
        "--india-gov",
        action="store_true",
        help="Scrape Featured Schemes from https://www.india.gov.in/my-government/schemes.",
    )
    parser.add_argument(
        "--myscheme",
        action="store_true",
        help=(
            "Scrape myScheme central ministry and state listing pages: "
            "https://www.myscheme.gov.in/search/ministry/all-ministries and "
            "https://www.myscheme.gov.in/search/state/all-states."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum cards per portal during scraping.")
    parser.add_argument("--watch", action="store_true", help="Continuously refresh at SCHEME_REFRESH_MINUTES.")
    parser.add_argument("--count", action="store_true", help="Print the number of schemes in PostgreSQL.")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Insert scraped schemes without BGE vectors. Useful to verify scraping/database writes quickly.",
    )
    args = parser.parse_args()

    try:
        if args.count:
            print(f"Vector database scheme count: {count_database()}")
            return

        if not args.json and not args.portals and not args.india_gov and not args.myscheme:
            parser.error("Provide --json, --portals, --india-gov, --myscheme, or --count")

        while True:
            count = 0
            if args.json:
                count += ingest_json(args.json, skip_embeddings=args.skip_embeddings)
            if args.portals:
                count += ingest_portals(args.portals, limit=args.limit, skip_embeddings=args.skip_embeddings)
            if args.india_gov:
                count += ingest_india_gov(limit=args.limit, skip_embeddings=args.skip_embeddings)
            if args.myscheme:
                count += ingest_myscheme(limit=args.limit, skip_embeddings=args.skip_embeddings)
            print(f"Ingested {count} schemes.")
            if not args.watch:
                break
            minutes = int(os.getenv("SCHEME_REFRESH_MINUTES", "360"))
            time.sleep(minutes * 60)
    except (RuntimeError, ScrapeError, json.JSONDecodeError, TypeError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print(
            "If this is a PostgreSQL connection error, make sure a pgvector-enabled "
            "PostgreSQL server is running and DATABASE_URL points to the correct host, port, database, and password."
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
