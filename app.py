import asyncio
import csv
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE / "a1_news.db"))
REGISTRY_PATH = BASE / "source_registry.csv"

MAX_SOURCES_PER_RUN = int(os.getenv("MAX_SOURCES_PER_RUN", "50"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "12"))
INGEST_MINUTES = int(os.getenv("INGEST_MINUTES", "10"))

KEYWORDS = [
    "terror", "terrorist", "bandit", "kidnap", "kidnapping",
    "insurgent", "insurgency", "military", "army", "navy",
    "air force", "police", "dss", "security", "attack",
    "explosion", "bomb", "crime", "election", "president",
    "governor", "national security", "defence", "defense",
    "maritime", "piracy", "oil", "pipeline", "coup", "war",
    "conflict"
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT,
            source_name TEXT,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            published TEXT,
            summary TEXT,
            category TEXT,
            priority TEXT,
            score INTEGER,
            verification_status TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def load_sources():
    if not REGISTRY_PATH.exists():
        return []

    with REGISTRY_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def score_article(title, summary, source):
    text = f"{title} {summary}".lower()

    try:
        score = int(source.get("verification_weight") or 50)
    except ValueError:
        score = 50

    hits = sum(1 for keyword in KEYWORDS if keyword in text)

    score += min(hits * 5, 25)

    if source.get("alert_priority", "").lower() == "critical":
        score += 10

    return min(score, 100)


def classify(score):
    if score >= 90:
        return "CRITICAL"
    if score >= 75:
        return "HIGH"
    if score >= 55:
        return "MEDIUM"
    return "LOW"


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def make_summary(entry):
    raw = clean_text(
        entry.get("summary")
        or entry.get("description")
        or ""
    )

    if len(raw) > 500:
        raw = raw[:497].rsplit(" ", 1)[0] + "..."

    return raw


def entry_url(entry):
    return (
        entry.get("link")
        or entry.get("id")
        or ""
    ).strip()


def find_feed_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for tag in soup.find_all("link"):
        typ = (tag.get("type") or "").lower()
        href = tag.get("href")

        if href and (
            "rss" in typ
            or "atom" in typ
            or href.lower().endswith(
                (".xml", "/feed", "/rss", "/atom")
            )
        ):
            links.append(urljoin(base_url, href))

    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()

        if any(
            x in low
            for x in ("/feed", "/rss", "/atom", ".xml")
        ):
            links.append(urljoin(base_url, href))

    return list(dict.fromkeys(links))[:5]


async def fetch_feed(client, source):
    url = source["url"]

    try:
        response = await client.get(
            url,
            follow_redirects=True
        )

        response.raise_for_status()

        content_type = (
            response.headers.get("content-type") or ""
        ).lower()

        parsed = feedparser.parse(response.content)

        if parsed.entries:
            return parsed.entries

        if (
            "html" in content_type
            or b"<html" in response.content[:1000].lower()
        ):
            for feed_url in find_feed_links(
                response.text,
                str(response.url)
            ):
                try:
                    feed_response = await client.get(
                        feed_url,
                        follow_redirects=True
                    )

                    parsed = feedparser.parse(
                        feed_response.content
                    )

                    if parsed.entries:
                        return parsed.entries

                except Exception:
                    continue

    except Exception:
        return []

    return []


async def ingest(limit=None):
    sources = load_sources()

    if not sources:
        return {
            "sources_checked": 0,
            "articles_added": 0
        }

    sources.sort(
        key=lambda source: (
            0 if source.get("level") == "A1" else 1,
            0 if source.get(
                "alert_priority", ""
            ).lower() == "critical" else 1,
            source.get("name", "")
        )
    )

    sources = sources[
        :limit or MAX_SOURCES_PER_RUN
    ]

    added = 0

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent":
            "A1-News-Intelligence/1.0"
        }
    ) as client:

        results = await asyncio.gather(
            *(
                fetch_feed(client, source)
                for source in sources
            ),
            return_exceptions=True
        )

    conn = db()

    for source, entries in zip(
        sources,
        results
    ):
        if isinstance(entries, Exception):
            continue

        for entry in entries[:20]:
            title = clean_text(
                entry.get("title", "")
            )

            url = entry_url(entry)

            if not title or not url:
                continue

            summary = make_summary(entry)

            score = score_article(
                title,
                summary,
                source
            )

            try:
                conn.execute(
                    """
                    INSERT INTO articles
                    (
                        source_code,
                        source_name,
                        title,
                        url,
                        published,
                        summary,
                        category,
                        priority,
                        score,
                        verification_status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.get("code"),
                        source.get("name"),
                        title,
                        url,
                        entry.get("published")
                        or entry.get("updated")
                        or "",
                        summary,
                        source.get(
                            "category",
                            "News"
                        ),
                        classify(score),
                        score,
                        "DEVELOPING",
                        utc_now()
                    )
                )

                added += 1

            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()

    return {
        "sources_checked": len(sources),
        "articles_added": added,
        "checked_at": utc_now()
    }


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app):
    init_db()

    scheduler.add_job(
        ingest,
        "interval",
        minutes=INGEST_MINUTES,
        id="news_ingest",
        replace_existing=True
    )

    scheduler.start()

    yield

    scheduler.shutdown(
        wait=False
    )


app = FastAPI(
    title="A1 News Intelligence",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
def home():
    return {
        "name": "A1 News Intelligence",
        "status": "online",
        "message":
            "News intelligence engine is running.",
        "endpoints": [
            "/health",
            "/sources",
            "/news",
            "/stats",
            "/run-ingest"
        ]
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service":
            "a1-news-intelligence"
    }


@app.get("/sources")
def sources():
    data = load_sources()

    return {
        "count": len(data),
        "sources": data
    }


@app.get("/news")
def news(
    limit: int = 25,
    priority: str | None = None
):
    limit = max(
        1,
        min(limit, 100)
    )

    conn = db()

    if priority:
        rows = conn.execute(
            """
            SELECT *
            FROM articles
            WHERE priority = ?
            ORDER BY score DESC,
                     created_at DESC
            LIMIT ?
            """,
            (
                priority.upper(),
                limit
            )
        ).fetchall()

    else:
        rows = conn.execute(
            """
            SELECT *
            FROM articles
            ORDER BY score DESC,
                     created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    conn.close()

    return {
        "count": len(rows),
        "articles": [
            dict(row)
            for row in rows
        ]
    }


@app.post("/run-ingest")
async def run_ingest(
    limit: int | None = None
):
    if limit is not None and limit < 1:
        raise HTTPException(
            400,
            "limit must be positive"
        )

    return await ingest(limit)


@app.get("/stats")
def stats():
    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0]

    critical = conn.execute(
        """
        SELECT COUNT(*)
        FROM articles
        WHERE priority='CRITICAL'
        """
    ).fetchone()[0]

    high = conn.execute(
        """
        SELECT COUNT(*)
        FROM articles
        WHERE priority='HIGH'
        """
    ).fetchone()[0]

    conn.close()

    return {
        "articles": total,
        "critical": critical,
        "high": high
    }
