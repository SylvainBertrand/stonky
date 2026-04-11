"""AAII and NAAIM sentiment data: scraping + CSV import."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AAIISentiment:
    week_ending: date
    bullish_pct: float
    neutral_pct: float
    bearish_pct: float
    bull_bear_spread: float  # bullish - bearish


def parse_aaii_csv(content: str) -> list[AAIISentiment]:
    """Parse AAII CSV. Expected columns: date, bullish, neutral, bearish."""
    results: list[AAIISentiment] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                week = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                bullish = float(row["bullish"])
                neutral = float(row["neutral"])
                bearish = float(row["bearish"])
                results.append(
                    AAIISentiment(
                        week_ending=week,
                        bullish_pct=bullish,
                        neutral_pct=neutral,
                        bearish_pct=bearish,
                        bull_bear_spread=round(bullish - bearish, 4),
                    )
                )
            except (KeyError, ValueError):
                continue
    except Exception:
        logger.warning("Failed to parse AAII CSV")
    return results


def parse_naaim_csv(content: str) -> list[dict]:
    """Parse NAAIM CSV. Expected columns: date, exposure."""
    results: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                week = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                exposure = float(row["exposure"])
                results.append({"week_ending": week, "exposure": exposure})
            except (KeyError, ValueError):
                continue
    except Exception:
        logger.warning("Failed to parse NAAIM CSV")
    return results


async def scrape_aaii() -> list[AAIISentiment]:
    """Scrape AAII sentiment survey page. Returns empty list on failure.

    Note: AAII blocks most automated user agents (403).  Use CSV import
    via POST /api/market/sentiment/import?source=aaii as the primary path.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.aaii.com/sentimentsurvey/sent_results",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html",
                },
            )
            resp.raise_for_status()
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                logger.warning("AAII: no table found on page")
                return []

            results: list[AAIISentiment] = []
            rows = table.find_all("tr")[1:]  # skip header
            for tr in rows[:52]:  # last 52 weeks max
                cells = tr.find_all("td")
                if len(cells) < 4:
                    continue
                try:
                    week_str = cells[0].get_text(strip=True)
                    week = datetime.strptime(week_str, "%m/%d/%Y").date()
                    bullish = float(cells[1].get_text(strip=True).replace("%", ""))
                    neutral = float(cells[2].get_text(strip=True).replace("%", ""))
                    bearish = float(cells[3].get_text(strip=True).replace("%", ""))
                    results.append(
                        AAIISentiment(
                            week_ending=week,
                            bullish_pct=bullish,
                            neutral_pct=neutral,
                            bearish_pct=bearish,
                            bull_bear_spread=round(bullish - bearish, 4),
                        )
                    )
                except (ValueError, IndexError):
                    continue
            return results
    except Exception:
        logger.exception("AAII scrape failed")
        return []


async def scrape_naaim() -> list[dict]:
    """Scrape NAAIM exposure index page. Returns empty list on failure."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.naaim.org/programs/naaim-exposure-index/",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html",
                },
            )
            resp.raise_for_status()
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                logger.warning("NAAIM: no table found on page")
                return []

            results: list[dict] = []
            rows = table.find_all("tr")[1:]
            for tr in rows[:52]:
                cells = tr.find_all("td")
                if len(cells) < 2:
                    continue
                try:
                    week_str = cells[0].get_text(strip=True)
                    week = datetime.strptime(week_str, "%m/%d/%Y").date()
                    exposure = float(cells[1].get_text(strip=True))
                    results.append({"week_ending": week, "exposure": exposure})
                except (ValueError, IndexError):
                    continue
            return results
    except Exception:
        logger.exception("NAAIM scrape failed")
        return []
