"""
IMDb scraper for trivia and goofs
"""

import httpx
from typing import List, Optional
from bs4 import BeautifulSoup


class IMDbScraper:
    """Scrape trivia and goofs from IMDb"""

    def __init__(self):
        self.base_url = "https://www.imdb.com"
        # Full browser headers. IMDb returns HTTP 202 + an Akamai/WAF
        # challenge page (empty <title>) for thin/bot-like clients.
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.imdb.com/",
            "Upgrade-Insecure-Requests": "1",
        }

    async def get_trivia_and_goofs(self, imdb_id: str) -> dict:
        """
        Get trivia and goofs for a movie

        Args:
            imdb_id: IMDb ID (e.g., "tt0468569")

        Returns:
            dict with 'trivia' and 'goofs' lists
        """
        if not imdb_id or not imdb_id.startswith("tt"):
            return {"trivia": [], "goofs": [], "total_items": 0}

        trivia = await self._get_trivia(imdb_id)
        goofs = await self._get_goofs(imdb_id)

        return {
            "trivia": trivia,
            "goofs": goofs,
            "total_items": len(trivia) + len(goofs),
        }

    def _log_non_200(self, page: str, status_code: int) -> None:
        if status_code == 202:
            print(
                f"  ⚠️  IMDb {page} blocked by WAF (HTTP 202) — "
                "Akamai challenge page, not trivia. Skipping HTML scrape."
            )
        else:
            print(f"  ⚠️  IMDb {page} request failed: {status_code}")

    async def _fetch_imdb_html(self, url: str, page: str) -> Optional[str]:
        """GET an IMDb page. Only return HTML when status is 200."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url, headers=self.headers, follow_redirects=True
            )
            if response.status_code != 200:
                self._log_non_200(page, response.status_code)
                return None
            return response.text

    async def _get_trivia(self, imdb_id: str) -> List[str]:
        """Get trivia items from IMDb"""
        try:
            url = f"{self.base_url}/title/{imdb_id}/trivia"
            html = await self._fetch_imdb_html(url, "trivia")
            if html is None:
                return []

            soup = BeautifulSoup(html, "html.parser")
            trivia_items = []
            trivia_divs = soup.find_all(
                "div", class_="ipc-html-content-inner-div"
            )

            for div in trivia_divs[:50]:
                text = div.get_text(strip=True)
                if text and len(text) > 20:
                    trivia_items.append(text)

            print(f"  ✓ Found {len(trivia_items)} IMDb trivia items")
            return trivia_items

        except Exception as e:
            print(f"  ⚠️  Error fetching IMDb trivia: {e}")
            return []

    async def _get_goofs(self, imdb_id: str) -> List[str]:
        """Get goofs from IMDb"""
        try:
            url = f"{self.base_url}/title/{imdb_id}/goofs"
            html = await self._fetch_imdb_html(url, "goofs")
            if html is None:
                return []

            soup = BeautifulSoup(html, "html.parser")
            goof_items = []
            goof_divs = soup.find_all(
                "div", class_="ipc-html-content-inner-div"
            )

            for div in goof_divs[:30]:
                text = div.get_text(strip=True)
                if text and len(text) > 20:
                    goof_items.append(text)

            print(f"  ✓ Found {len(goof_items)} IMDb goofs")
            return goof_items

        except Exception as e:
            print(f"  ⚠️  Error fetching IMDb goofs: {e}")
            return []
