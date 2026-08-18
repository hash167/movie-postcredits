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



    def test_typeahead_uses_get_search_query_param(self):
        with open("frontend/useMovieSearch.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('params.set(\'query\'', src.replace('"', "'"))
        self.assertIn('/search?', src)
        self.assertIn('TYPEAHEAD_DEBOUNCE_MS', src)
        self.assertIn('300', src)
        self.assertIn('if (cancelled)', src)
        self.assertIn('findCdnMovieById', src)
        self.assertIn('movie_id', src)

    def test_typeahead_never_ranks_with_includes(self):
        """Short titles (It, Up, Her, Sh) must not win via query.includes(title)."""
        files = [
            "frontend/useMovieSearch.js",
            "frontend/MovieSearchComponent.js",
        ]
        banned = (
            "searchInCDN",
            "title.includes",
            "term.includes",
            "query.includes",
            "movieTitle.includes",
            "movie.title.toLowerCase().includes",
        )
        for path in files:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            for token in banned:
                self.assertNotIn(token, src, f"{path} still has {token}")

    def test_search_results_list_is_rendered(self):
        with open("frontend/MovieSearchComponent.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Search results", src)
        self.assertIn("setChosen", src)

if __name__ == "__main__":
    unittest.main()
