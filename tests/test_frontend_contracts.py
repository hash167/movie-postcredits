import unittest


class FrontendContractTests(unittest.TestCase):
    def test_home_lists_theater_movies_without_requiring_eggs(self):
        with open("frontend/MovieSearchComponent.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Now in Theaters (", src)
        self.assertIn("m.year >= currentYear - 1", src)
        self.assertNotIn("hasContent", src)
        self.assertNotIn(
            "No movies in theaters with easter eggs yet", src
        )

    def test_clearing_search_resets_movie_card(self):
        with open("frontend/useMovieSearch.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("if (!movieTitle)", src)
        self.assertIn("setMovie(null)", src)
        self.assertIn("setError(null)", src)
        self.assertIn("setSource(null)", src)

    def test_config_is_same_origin(self):
        with open("frontend/config.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("window.location.origin", src)
        self.assertIn("window.rewritePoster", src)
        self.assertIn("/tmdb-image/", src)
        self.assertIn("/movies/", src)

    def test_nginx_proxies_required_paths(self):
        with open("frontend/nginx.conf", encoding="utf-8") as fh:
            src = fh.read()
        for path in (
            "/search",
            "/stats",
            "/health",
            "/movie/",
            "/movies/tier/",
            "/movies/",
            "/tmdb-image/",
        ):
            self.assertIn(path, src)
        self.assertIn("minio:9000/movies/", src)
        self.assertIn("image.tmdb.org", src)


if __name__ == "__main__":
    unittest.main()
