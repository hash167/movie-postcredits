import httpx
from typing import List, Dict, Optional
from src.config import settings


class TMDBClient:
    def __init__(self):
        self.base_url = "https://api.themoviedb.org/3"
        self.api_key = settings.tmdb_api_key
        self.image_base = "https://image.tmdb.org/t/p/w500"

    async def get_movies_in_theaters(self, limit: int = 50) -> List[Dict]:
        movies = []
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/movie/now_playing"
            params = {
                "api_key": self.api_key,
                "language": "en-US",
                "region": "US",
                "page": 1,
            }
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            movies.extend(data["results"])
            return movies[:limit]

    async def get_popular_movies(self, limit: int = 1000) -> List[Dict]:
        movies = []
        for page in range(1, min((limit + 19) // 20, 500) + 1):
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/movie/popular"
                params = {
                    "api_key": self.api_key,
                    "language": "en-US",
                    "page": page
                }
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                movies.extend(data["results"])
                if len(movies) >= limit:
                    break
        return movies[:limit]

    async def get_recent_releases(self, years: int = 2) -> List[Dict]:
        from datetime import datetime

        movies = []
        current_year = datetime.now().year
        start_year = current_year - years
        for year in range(start_year, current_year + 1):
            for page in range(1, 3):
                async with httpx.AsyncClient() as client:
                    url = f"{self.base_url}/discover/movie"
                    params = {
                        "api_key": self.api_key,
                        "language": "en-US",
                        "primary_release_year": year,
                        "sort_by": "popularity.desc",
                        "page": page,
                    }
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    if not data["results"]:
                        break
                    movies.extend(data["results"])
        return movies

    async def search_movie(
        self, query: str, year: Optional[int] = None
    ) -> Optional[Dict]:
        url = f"{self.base_url}/search/movie"
        params = {"api_key": self.api_key, "query": query, "language": "en-US"}
        if year:
            params["year"] = year
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data["results"][0] if data.get("results") else None

    async def get_movie_keywords(self, movie_id: int) -> List[Dict]:
        """Dedicated /movie/{id}/keywords call."""
        url = f"{self.base_url}/movie/{movie_id}/keywords"
        params = {"api_key": self.api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        return data.get("keywords") or data.get("results") or []

    async def get_movie_details(self, movie_id: int) -> Optional[Dict]:
        url = f"{self.base_url}/movie/{movie_id}"
        params = {
            "api_key": self.api_key,
            "language": "en-US",
            "append_to_response": "keywords",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        from src.insights import extract_keywords

        if not extract_keywords(data):
            try:
                keywords = await self.get_movie_keywords(movie_id)
                if keywords:
                    data["keywords"] = {"keywords": keywords}
            except Exception as exc:
                print(f"  ⚠️  TMDB keywords fallback failed: {exc}")
        return data

    def format_movie(self, movie_data: Dict, tier: str) -> Dict:
        release_date = movie_data.get("release_date")
        year = 0
        if release_date:
            year = int(release_date[:4])

        poster_path = None
        if movie_data.get("poster_path"):
            poster_path = f"{self.image_base}{movie_data['poster_path']}"

        return {
            "id": movie_data["id"],
            "title": movie_data["title"],
            "year": year,
            "release_date": release_date or "",
            "runtime_minutes": movie_data.get("runtime", 0),
            "poster_path": poster_path,
            "overview": movie_data.get("overview", ""),
            "vote_average": movie_data.get("vote_average", 0.0),
            "popularity": movie_data.get("popularity", 0.0),
            "tier": tier,
            "imdb_id": movie_data.get("imdb_id"),
        }
