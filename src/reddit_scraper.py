"""
Reddit scraper and OpenAI analyzer for post-credits scenes and easter eggs
"""

import httpx
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from src.config import settings
from src.models import RedditInsights, PostCreditsScene, EasterEgg
from src.imdb_scraper import IMDbScraper


class RedditScraper:
    """Scraper for Reddit posts about post-credits scenes and easter eggs"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.reddit_search_url = "https://www.reddit.com/search.json"
        self.imdb_scraper = IMDbScraper()

        # Keywords to search for
        self.post_credits_keywords = [
            "post credits",
            "post-credits",
            "after credits",
            "end credits scene",
            "post credit scene",
            "stay for credits",
            "mid credits",
            "mid-credits",
        ]

        self.easter_egg_keywords = [
            "easter egg",
            "hidden detail",
            "reference",
            "cameo",
            "did you notice",
        ]

    async def search_reddit(self, query: str, limit: int = 100) -> List[Dict]:
        """Search Reddit using the public JSON API"""
        results = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Search for post-credits mentions
            for keyword in self.post_credits_keywords[:3]:  # Limit API calls
                search_query = f"{query} {keyword}"
                params = {
                    "q": search_query,
                    "limit": 25,
                    "sort": "relevance",
                    "t": "all",
                }

                try:
                    response = await client.get(
                        self.reddit_search_url,
                        params=params,
                        headers={"User-Agent": "MoviePostCreditsBot/1.0"},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        for post in data.get("data", {}).get("children", []):
                            post_data = post.get("data", {})
                            permalink = post_data.get("permalink", "")
                            results.append(
                                {
                                    "title": post_data.get("title", ""),
                                    "body": post_data.get("selftext", ""),
                                    "subreddit": post_data.get(
                                        "subreddit", ""
                                    ),
                                    "score": post_data.get("score", 0),
                                    "url": f"https://reddit.com{permalink}",
                                    "created": post_data.get("created_utc", 0),
                                }
                            )

                    # Rate limiting
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"Error searching Reddit for '{search_query}': {e}")
                    continue

            # Search for easter eggs
            for keyword in self.easter_egg_keywords[:2]:
                search_query = f"{query} {keyword}"
                params = {
                    "q": search_query,
                    "limit": 15,
                    "sort": "top",
                    "t": "year",
                }

                try:
                    response = await client.get(
                        self.reddit_search_url,
                        params=params,
                        headers={"User-Agent": "MoviePostCreditsBot/1.0"},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        for post in data.get("data", {}).get("children", []):
                            post_data = post.get("data", {})
                            permalink = post_data.get("permalink", "")
                            results.append(
                                {
                                    "title": post_data.get("title", ""),
                                    "body": post_data.get("selftext", ""),
                                    "subreddit": post_data.get(
                                        "subreddit", ""
                                    ),
                                    "score": post_data.get("score", 0),
                                    "url": f"https://reddit.com{permalink}",
                                    "created": post_data.get("created_utc", 0),
                                }
                            )

                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"Error searching Reddit for '{search_query}': {e}")
                    continue

        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for result in results:
            if result["url"] not in seen_urls:
                seen_urls.add(result["url"])
                unique_results.append(result)

        return unique_results[:limit]

    async def analyze_with_gpt(
        self, movie_title: str, posts: List[Dict], imdb_data: Optional[dict] = None
    ) -> Optional[RedditInsights]:
        """Use OpenAI to analyze Reddit posts for insights"""

        if not posts:
            return None

        # Prepare context from Reddit posts
        context = []
        for i, post in enumerate(posts[:20], 1):
            context.append(f"Post {i} (score: {post['score']}):")
            context.append(f"Title: {post['title']}")
            if post["body"]:
                # Limit body length
                context.append(f"Body: {post['body'][:500]}")
            context.append(f"URL: {post['url']}\n")

        context_text = "\n".join(context)

        # Add IMDb data to prompt if available
        imdb_section = ""
        if imdb_data and (imdb_data.get('trivia') or imdb_data.get('goofs')):
            trivia_list = "\n".join([f"- {t[:300]}" for t in imdb_data.get('trivia', [])[:15]])
            goofs_list = "\n".join([f"- {g[:300]}" for g in imdb_data.get('goofs', [])[:10]])
            
            imdb_section = f"""

IMDb Trivia:
{trivia_list if trivia_list else "(none)"}

IMDb Goofs:
{goofs_list if goofs_list else "(none)"}
"""

        prompt = (
            (
                f"You are analyzing Reddit discussions and IMDb trivia about the movie "
                f'"{movie_title}" to extract:\n'
                "1. Post-credits scene information\n"
                "2. Easter eggs and hidden details\n\n"
                f"Reddit posts:\n{context_text}\n"
                f"{imdb_section}\n\n"
                "Please provide a JSON response with this exact structure:"
            )
            + """
{{
  "post_credits": {{
    "has_scene": true/false,
    "scene_count": number (0 if no scenes),
    "descriptions": ["mid-credits desc", "post-credits desc"],
    "worth_staying": true/false/null,
    "spoiler_free_hint": "A brief spoiler-free hint about what to expect"
  }},
  "easter_eggs": [
    {{
      "detail": "Description of the easter egg or hidden detail",
      "significance": "Why it's significant or what it references",
      "confidence": "high/medium/low",
      "source_url": "URL from Reddit if available"
    }}
  ]
}}

Guidelines:
- Only include information explicitly mentioned in the posts
- For post_credits.descriptions, include separate entries
  for mid-credits and post-credits scenes
- Keep descriptions spoiler-light but informative
- Only include easter eggs that are clearly explained
- If no clear information is found, return has_scene: false
  and empty easter_eggs array
"""
        )

        try:
            system_msg = (
                "You are a helpful assistant that analyzes movie "
                "discussions to extract post-credits scene information "
                "and easter eggs. Always respond with valid JSON."
            )
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )

            import json

            result = json.loads(response.choices[0].message.content)

            # Parse into Pydantic models
            post_credits_data = result.get("post_credits", {})
            post_credits = PostCreditsScene(
                has_scene=post_credits_data.get("has_scene", False),
                scene_count=post_credits_data.get("scene_count", 0),
                descriptions=post_credits_data.get("descriptions", []),
                worth_staying=post_credits_data.get("worth_staying"),
                spoiler_free_hint=post_credits_data.get("spoiler_free_hint"),
            )

            easter_eggs = [
                EasterEgg(
                    detail=egg.get("detail", ""),
                    significance=egg.get("significance", ""),
                    confidence=egg.get("confidence", "medium"),
                    source_url=egg.get("source_url"),
                )
                for egg in result.get("easter_eggs", [])
            ]

            insights = RedditInsights(
                easter_eggs=easter_eggs,
                post_credits=post_credits,
                reddit_discussion_count=len(posts),
                source_urls=[p["url"] for p in posts[:10]],
            )

            return insights

        except Exception as e:
            print(f"Error analyzing with GPT: {e}")
            return None

    async def scrape_movie_insights(
        self, movie_title: str, year: Optional[int] = None, imdb_id: Optional[str] = None
    ) -> Optional[RedditInsights]:
        """Main method to scrape and analyze Reddit + IMDb for a movie"""
        search_query = movie_title
        if year:
            search_query = f"{movie_title} {year}"

        print(f"Searching Reddit for: {search_query}")
        posts = await self.search_reddit(search_query)
        print(f"Found {len(posts)} relevant Reddit posts")

        # Also fetch IMDb trivia and goofs if we have IMDb ID
        imdb_data = None
        if imdb_id:
            print(f"Fetching IMDb trivia & goofs for: {imdb_id}")
            imdb_data = await self.imdb_scraper.get_trivia_and_goofs(imdb_id)
            if imdb_data['total_items'] > 0:
                print(f"  ✓ Found {imdb_data['total_items']} IMDb items")

        if not posts and (not imdb_data or imdb_data['total_items'] == 0):
            print("  ⚠️  No Reddit posts or IMDb data found")
            return None

        print("Analyzing with OpenAI...")
        insights = await self.analyze_with_gpt(movie_title, posts, imdb_data)

        return insights
