const { useState, useEffect } = React;

const TYPEAHEAD_DEBOUNCE_MS = 300;

const cdnDataCache = {
  theaters: null,
  popular: null,
  recent: null,
  'on-demand': null,
};

window.preloadCDNData = async function() {
  const tiers = ['theaters', 'popular', 'recent', 'on-demand'];
  const cacheBuster = Date.now();
  await Promise.all(
    tiers.map(async (tier) => {
      try {
        const response = await fetch(`${window.CDN_BASE}${tier}-movies.json?v=${cacheBuster}`);
        const data = await response.json();
        cdnDataCache[tier] = data;
        console.log(`✅ Loaded ${tier}: ${data.movieCount} movies`);
        const eggsCount = data.movies ? data.movies.filter(m => m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0).length : 0;
        console.log(`   📊 Movies with easter eggs: ${eggsCount}`);
      } catch (e) {
        console.warn(`Failed to load ${tier} from CDN:`, e);
      }
    })
  );
};

function cdnMovieHasInsights(movie) {
  if (!movie) return false;
  const eggs = movie.easterEggs && Array.isArray(movie.easterEggs) ? movie.easterEggs : [];
  const hasEggs = eggs.some(function (e) {
    if (!e) return false;
    if (typeof e === 'string') return !!String(e).trim();
    return !!(e.detail || e.description || e.title);
  });
  const hasScene = !!(movie.postCredits && movie.postCredits.hasScene);
  return hasEggs || hasScene;
}

function findCdnMovieById(movieId) {
  if (movieId == null) return null;
  for (const tier of ['theaters', 'popular', 'recent', 'on-demand']) {
    const data = cdnDataCache[tier];
    if (!data || !data.movies) continue;
    const found = data.movies.find((movie) => movie.id === movieId);
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
    overview: item.overview || '',
  };
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
        source: 'api-processing',
      };
      setMovie(placeholder);
      setSource('api-processing');
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
          setMovie({ ...exact.movie, source: 'cdn', tier: exact.tier, instant: true });
          setSource('cdn');
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
                const hasEggs = eggs.some((e) => e && (e.detail || e.description || e.title || (typeof e === 'string' && e.trim())));
                const hasScene = cached.postCredits && cached.postCredits.hasScene;
                if (hasEggs || hasScene) {
                  if (cancelled) return;
                  setMovie({ ...cached, source: 'api-cached', instant: false });
                  setSource('api-cached');
                  setLoading(false);
                  return;
                }
              }
            } catch (e) {
              console.warn('GET /movie failed, falling back to POST /search', e);
            }
          }
          const response = await fetch(`${window.API_BASE}/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: selectedTitle,
              year: selectedYear,
              movie_id: selectedId || undefined,
            }),
          });
          const data = await response.json();
          if (cancelled) return;
          if (!response.ok) {
            setError((data && data.detail) || ('HTTP ' + response.status));
            return;
          }
          const ready = (data.easterEggs && data.easterEggs.length) || (data.postCredits && data.postCredits.hasScene);
          if (ready) {
            setMovie({ ...data, source: 'api-cached', instant: false });
            setSource('api-cached');
            stopPolling();
            return;
          }
          setMovie((prev) => ({
            ...(prev || placeholder),
            id: data.id || (prev && prev.id) || selectedId,
            title: data.title || (prev && prev.title) || selectedTitle,
            year: data.year || (prev && prev.year) || selectedYear,
            posterPath: data.posterPath || (prev && prev.posterPath) || placeholder.posterPath,
            source: 'api-processing',
          }));
          setSource('api-processing');
          const pollId = data.id || selectedId;
          if (pollId) {
            stopPolling();
            stopPolling = startAutoPolling(pollId);
            if (cancelled) stopPolling();
          }
        } catch (e) {
          if (cancelled) return;
          if (selectedId) {
            stopPolling();
            stopPolling = startAutoPolling(selectedId);
            if (cancelled) stopPolling();
          } else {
            setError(e.message || 'API error');
          }
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
        params.set('query', requestQuery);
        if (requestYear) params.set('year', String(requestYear));
        const response = await fetch(`${window.API_BASE}/search?${params.toString()}`);
        const data = await response.json();
        if (cancelled) return;
        if (!response.ok) {
          setError((data && data.detail) || ('HTTP ' + response.status));
          setResults([]);
          setLoading(false);
          return;
        }
        const list = Array.isArray(data.results) ? data.results.map(toResult) : [];
        setResults(list);
        setLoading(false);
      } catch (e) {
        if (cancelled) return;
        setError(e.message || 'API error');
        setResults([]);
        setLoading(false);
      }
    }, TYPEAHEAD_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [movieTitle, year, selectedTitle, selectedYear, selectedId, selectedPoster]);

  function startAutoPolling(movieId) {
    let pollAttempts = 0;
    const maxPolls = 20;
    const pollInterval = setInterval(async () => {
      pollAttempts++;
      console.log(`🔄 Auto-polling attempt ${pollAttempts}/${maxPolls}...`);
      try {
        const response = await fetch(`${window.API_BASE}/movie/${movieId}`);
        if (response.ok) {
          const data = await response.json();
          const hasPostCredits = data.postCredits && data.postCredits.hasScene !== undefined;
          const hasEasterEggs = data.easterEggs && Array.isArray(data.easterEggs) && data.easterEggs.length > 0;
          if (hasPostCredits || hasEasterEggs || pollAttempts >= maxPolls) {
            console.log('✅ Processing complete! Updating movie data...');
            setMovie({ ...data, source: 'api-cached' });
            setSource('api-cached');
            clearInterval(pollInterval);
            if (hasPostCredits || hasEasterEggs) {
              console.log('🎉 Movie analysis complete!');
              setTimeout(async () => {
                try {
                  const cacheBuster = Date.now();
                  const response2 = await fetch(`${window.CDN_BASE}on-demand-movies.json?v=${cacheBuster}`);
                  const onDemandData = await response2.json();
                  cdnDataCache['on-demand'] = onDemandData;
                  console.log('🔄 Reloaded on-demand movies from MinIO');
                } catch (e) {
                  console.warn('Failed to reload on-demand:', e);
                }
              }, 2000);
            }
          }
        }
      } catch (e) {
        console.error('Polling error:', e);
        if (pollAttempts >= maxPolls) {
          clearInterval(pollInterval);
        }
      }
    }, 5000);
    return () => clearInterval(pollInterval);
  }

  return { results, movie, loading, source, error, pollCount };
};

window.getTheatersData = function() {
  return cdnDataCache['theaters'];
};

window.getOnDemandData = function() {
  return cdnDataCache['on-demand'];
};
