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
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.imdb.com/",
        }

    async def get_trivia_and_goofs(self, imdb_id: str) -> dict:
        """
        Get trivia and goofs for a movie
        
        Args:
            imdb_id: IMDb ID (e.g., "tt0468569")
            
        Returns:
            dict with 'trivia' and 'goofs' lists
        """
        if not imdb_id or not imdb_id.startswith('tt'):
            return {"trivia": [], "goofs": []}

        trivia = await self._get_trivia(imdb_id)
        goofs = await self._get_goofs(imdb_id)

        return {
            "trivia": trivia,
            "goofs": goofs,
            "total_items": len(trivia) + len(goofs)
        }

    async def _get_trivia(self, imdb_id: str) -> List[str]:
        """Get trivia items from IMDb"""
        try:
            url = f"{self.base_url}/title/{imdb_id}/trivia"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self.headers, follow_redirects=True)
                
                if response.status_code != 200:
                    # 202 = IMDb/Akamai bot challenge (empty interstitial), not a real trivia page
                    print(
                        f"  ⚠️  IMDb trivia blocked ({response.status_code}); "
                        "WAF challenge, not a missing page"
                    )
                    return []

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find trivia items
                trivia_items = []
                
                # IMDb trivia is in divs with class "ipc-html-content-inner-div"
                trivia_divs = soup.find_all('div', class_='ipc-html-content-inner-div')
                
                for div in trivia_divs[:50]:  # Limit to 50 items
                    text = div.get_text(strip=True)
                    if text and len(text) > 20:  # Filter out very short items
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
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self.headers, follow_redirects=True)
                
                if response.status_code != 200:
                    print(
                        f"  ⚠️  IMDb goofs blocked ({response.status_code}); "
                        "WAF challenge, not a missing page"
                    )
                    return []

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find goof items
                goof_items = []
                
                # IMDb goofs are in divs with class "ipc-html-content-inner-div"
                goof_divs = soup.find_all('div', class_='ipc-html-content-inner-div')
                
                for div in goof_divs[:30]:  # Limit to 30 items
                    text = div.get_text(strip=True)
                    if text and len(text) > 20:
                        goof_items.append(text)
                
                print(f"  ✓ Found {len(goof_items)} IMDb goofs")
                return goof_items

        except Exception as e:
            print(f"  ⚠️  Error fetching IMDb goofs: {e}")
            return []
