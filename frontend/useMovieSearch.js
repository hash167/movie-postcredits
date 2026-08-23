(() => {
  const { useState, useEffect } = React;
  const TYPEAHEAD_DEBOUNCE_MS = 300;
  const cdnDataCache = {
    theaters: null,
    popular: null,
    recent: null,
    "on-demand": null
  };
  async function fetchJson(url, ms) {
    const controller = new AbortController();
    const timer = setTimeout(function() {
      controller.abort();
    }, ms);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error("HTTP " + response.status);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }
  window.preloadCDNData = async function() {
    const tiers = ["theaters", "popular", "recent", "on-demand"];
    const cacheBuster = Date.now();
    await Promise.all(
      tiers.map(async (tier) => {
        const name = tier + "-movies.json";
        const urls = [
          "/" + name + "?v=" + cacheBuster,
          (window.CDN_BASE || "") + name + "?v=" + cacheBuster
        ];
        for (const url of urls) {
          try {
            const data = await fetchJson(url, 4e3);
            cdnDataCache[tier] = data;
            console.log("Loaded " + tier + ": " + (data.movieCount || 0) + " movies from " + url);
            return;
          } catch (e) {
            console.warn("Failed " + url, e);
          }
        }
        cdnDataCache[tier] = { tier, movieCount: 0, movies: [] };
      })
    );
  };
  function cdnMovieHasInsights(movie) {
    if (!movie) return false;
    const eggs = movie.easterEggs && Array.isArray(movie.easterEggs) ? movie.easterEggs : [];
    const hasEggs = eggs.some(function(e) {
      if (!e) return false;
      if (typeof e === "string") return !!String(e).trim();
      return !!(e.detail || e.description || e.title);
    });
    const hasScene = !!(movie.postCredits && movie.postCredits.hasScene);
    return hasEggs || hasScene;
  }
  function findCdnMovieById(movieId) {
    if (movieId == null) return null;
    for (const tier of ["theaters", "popular", "recent", "on-demand"]) {
      const data = cdnDataCache[tier];
      if (!data || !data.movies) continue;
      const found = data.movies.find(function(movie) {
        return movie.id === movieId;
      });
      if (found) return { movie: found, tier };
    }
    return null;
  }
  function toResult(item) {
    return {
      id: item.id,
      title: item.title,
      year: item.year,
      posterPath: item.posterPath || item.poster_path || null,
      overview: item.overview || ""
    };
  }
  function formatApiDetail(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map(function(item) {
        if (item == null) return "";
        if (typeof item === "string") return item;
        if (typeof item === "object" && item.msg) return String(item.msg);
        try { return JSON.stringify(item); } catch (e) { return String(item); }
      }).filter(Boolean).join("; ");
    }
    if (typeof detail === "object") {
      if (detail.msg) return String(detail.msg);
      try { return JSON.stringify(detail); } catch (e) { return String(detail); }
    }
    return String(detail);
  }
  function searchErrorMessage(err, status) {
    const raw = err && err.message ? String(err.message) : "";
    if (raw === "The string did not match the expected pattern.") {
      return "Search request failed";
    }
    const statusBit = status ? " (HTTP " + status + ")" : "";
    return "Search failed" + statusBit;
  }
  function parseSearchYear(year) {
    const n = typeof year === "number" ? year : parseInt(year, 10);
    if (!Number.isFinite(n) || n !== Math.floor(n)) return null;
    if (n < 1880 || n > 2100) return null;
    return n;
  }
  const FRESH_KEY = "movieFreshExtracts";
  function loadFreshIds() {
    try {
      const raw = sessionStorage.getItem(FRESH_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }
  function rememberFreshExtract(movieId) {
    if (movieId == null) return;
    const id = Number(movieId);
    const next = loadFreshIds().filter(function(x) { return Number(x) !== id; });
    next.unshift(id);
    try { sessionStorage.setItem(FRESH_KEY, JSON.stringify(next.slice(0, 50))); } catch (e) {}
  }
  function isFreshExtract(movieId) {
    if (movieId == null) return false;
    return loadFreshIds().some(function(x) { return Number(x) === Number(movieId); });
  }
  window.useMovieSearch = function(movieTitle, year, selected) {
    const [movie, setMovie] = useState(null);
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [source, setSource] = useState(null);
    const [error, setError] = useState(null);
    const [pollCount, setPollCount] = useState(0);
    const selectedTitle = selected && selected.title;
    const selectedYear = selected && selected.year;
    const selectedId = selected && selected.id;
    const selectedPoster = selected && (selected.posterPath || selected.poster_path);
    useEffect(() => {
      if (selectedTitle) {
        const placeholder = {
          id: selectedId,
          title: selectedTitle,
          year: selectedYear,
          posterPath: selectedPoster || null,
          source: "api-processing"
        };
        setMovie(placeholder);
        setSource("api-processing");
        setLoading(false);
        setError(null);
        setPollCount(0);
        setResults([]);
        let cancelled = false;
        let stopPolling = () => {};
        async function loadDetail() {
          const exact = findCdnMovieById(selectedId);
          if (exact && exact.movie && cdnMovieHasInsights(exact.movie)) {
            if (cancelled) return;
            setMovie({ ...exact.movie, source: "cdn", tier: exact.tier, instant: true });
            setSource("cdn");
            setLoading(false);
            return;
          }
          try {
            if (selectedId) {
              try {
                const existing = await fetch(`${window.API_BASE}/movie/${selectedId}`);
                if (existing.ok) {
                  const cached = await existing.json();
                  const eggs = cached.easterEggs && Array.isArray(cached.easterEggs) ? cached.easterEggs : [];
                  const hasEggs = eggs.some((e) => e && (e.detail || e.description || e.title || (typeof e === "string" && String(e).trim())));
                  const hasScene = cached.postCredits && cached.postCredits.hasScene;
                  if (hasEggs || hasScene) {
                    if (cancelled) return;
                    const full = await hydrateFromMovie(selectedId || cached.id, cached);
                    const src = isFreshExtract(selectedId || cached.id) ? "api-fresh" : "api-cached";
                    setMovie({ ...full, source: src, instant: false });
                    setSource(src);
                    setLoading(false);
                    return;
                  }
                }
              } catch (e) {
                console.warn("GET /movie failed, falling back to POST /search", e);
              }
            }
            fetch(`${window.API_BASE}/search`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ query: selectedTitle, year: selectedYear, movie_id: selectedId || undefined })
            }).then(async (response) => {
              const data = await response.json();
              if (cancelled) return;
              if (!response.ok) {
                setError(formatApiDetail(data && data.detail) || ("HTTP " + response.status));
                return;
              }
              const ready = (data.easterEggs && data.easterEggs.length) || (data.postCredits && data.postCredits.hasScene);
              if (ready || hasEggItems(data)) {
                const id = data.id || selectedId;
                const full = id ? await hydrateFromMovie(id, data) : data;
                rememberFreshExtract(id);
                setMovie({ ...full, source: "api-fresh", instant: false });
                setSource("api-fresh");
                stopPolling();
                return;
              }
              setMovie((prev) => ({
                ...(prev || placeholder),
                id: data.id || (prev && prev.id) || selectedId,
                title: data.title || (prev && prev.title) || selectedTitle,
                year: data.year || (prev && prev.year) || selectedYear,
                posterPath: data.posterPath || (prev && prev.posterPath) || placeholder.posterPath,
                source: "api-processing"
              }));
              setSource("api-processing");
              const pollId = data.id || selectedId;
              if (pollId) {
                stopPolling();
                stopPolling = startAutoPolling(pollId);
                if (cancelled) stopPolling();
              }
            }).catch((e) => {
              if (cancelled) return;
              if (selectedId) {
                stopPolling();
                stopPolling = startAutoPolling(selectedId);
                if (cancelled) stopPolling();
              } else {
                setError(e.message || "API error");
              }
            });
          } catch (e) {
            if (cancelled) return;
            setError(e.message || "API error");
          }
        }
        loadDetail();
        return () => {
          cancelled = true;
          stopPolling();
        };
      }
      setMovie(null);
      setSource(null);
      if (!movieTitle) {
        setResults([]);
        setLoading(false);
        setError(null);
        return;
      }
      if (!String(movieTitle).trim()) {
        setResults([]);
        setLoading(false);
        setError(null);
        return;
      }
      setResults([]);
      setLoading(true);
      setError(null);
      let cancelled = false;
      const requestQuery = String(movieTitle).trim();
      const requestYear = year || undefined;
      const timer = setTimeout(async () => {
        try {
          const params = new URLSearchParams();
          params.set("q", requestQuery);
          const validYear = parseSearchYear(requestYear);
          if (validYear != null) params.set("year", String(validYear));
          const response = await fetch(`${window.API_BASE}/search?${params.toString()}`);
          const data = await response.json();
          if (cancelled) return;
          if (!response.ok) {
            setError(formatApiDetail(data && data.detail) || ("HTTP " + response.status));
            setResults([]);
            setLoading(false);
            return;
          }
          const list = Array.isArray(data.results) ? data.results.map(toResult) : [];
          setResults(list);
          setLoading(false);
        } catch (e) {
          if (cancelled) return;
          setError(searchErrorMessage(e));
          setResults([]);
          setLoading(false);
        }
      }, TYPEAHEAD_DEBOUNCE_MS);
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }, [movieTitle, year, selectedTitle, selectedYear, selectedId, selectedPoster]);
    function eggList(data) {
      return data && Array.isArray(data.easterEggs) ? data.easterEggs : null;
    }
    function hasEggItems(data) {
      const eggs = eggList(data);
      if (!eggs) return false;
      return eggs.some(function(e) {
        if (!e) return false;
        if (typeof e === "string") return !!String(e).trim();
        return !!(e.detail || e.description || e.title);
      });
    }
    function extractIsFinished(data) {
      if (!data) return false;
      if (hasEggItems(data)) return true;
      const job = data.jobStatus || data.extractStatus || data.job_status;
      if (job === "done" || job === "failed") return true;
      if (data.postCredits && data.postCredits.hasScene === true) return true;
      if (data.postCredits && data.postCredits.confidence === "processing") return false;
      return false;
    }
    async function hydrateFromMovie(movieId, fallback) {
      try {
        const response = await fetch(`${window.API_BASE}/movie/${movieId}`);
        if (response.ok) {
          const latest = await response.json();
          return {
            ...(fallback || {}),
            ...latest,
            easterEggs: eggList(latest) || eggList(fallback) || [],
            postCredits: latest.postCredits != null ? latest.postCredits : (fallback && fallback.postCredits)
          };
        }
      } catch (e) {
        console.warn("hydrate GET /movie failed", e);
      }
      return fallback;
    }
    function startAutoPolling(movieId) {
      let pollAttempts = 0;
      const maxPolls = 90;
      const pollInterval = setInterval(async () => {
        pollAttempts++;
        console.log(`\u{1F504} Auto-polling attempt ${pollAttempts}/${maxPolls}...`);
        try {
          const response = await fetch(`${window.API_BASE}/movie/${movieId}`);
          if (response.ok) {
            const data = await response.json();
            // Do NOT treat postCredits.hasScene === false as complete.
            // Placeholder / mid-extract rows often have hasScene=false and empty eggs.
            if (extractIsFinished(data) || pollAttempts >= maxPolls) {
              const full = await hydrateFromMovie(movieId, data);
              console.log("\u2705 Processing complete! Updating movie data...");
              rememberFreshExtract(movieId || (full && full.id));
              setMovie({ ...full, source: "api-fresh" });
              setSource("api-fresh");
              clearInterval(pollInterval);
              if (hasEggItems(full) || (full.postCredits && full.postCredits.hasScene)) {
                console.log("\u{1F389} Movie analysis complete!");
                setTimeout(async () => {
                  try {
                    const cacheBuster = Date.now();
                    const response2 = await fetch((window.CDN_BASE || "/") + "on-demand-movies.json?v=" + cacheBuster);
                    const onDemandData = await response2.json();
                    cdnDataCache["on-demand"] = onDemandData;
                    console.log("\u{1F504} Reloaded on-demand movies from MinIO");
                  } catch (e) {
                    console.warn("Failed to reload on-demand:", e);
                  }
                }, 2e3);
              }
            }
          }
        } catch (e) {
          console.error("Polling error:", e);
          if (pollAttempts >= maxPolls) {
            clearInterval(pollInterval);
          }
        }
      }, 5e3);
      return () => clearInterval(pollInterval);
    }
    return { results, movie, loading, source, error, pollCount };
  };
  window.getTheatersData = function() {
    return cdnDataCache["theaters"];
  };
  window.getOnDemandData = function() {
    return cdnDataCache["on-demand"];
  };
})();
