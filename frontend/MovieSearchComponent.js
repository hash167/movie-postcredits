const { useState, useEffect } = React;

function posterSrc(url) {
  return window.rewritePoster ? window.rewritePoster(url) : url;
}

function isWorthStaying(value) {
  return value === true || value === 'yes' || value === 'true';
}

function eggHeading(egg) {
  if (typeof egg === 'string') return egg;
  return egg.detail || egg.title || egg.description || '';
}

function eggBody(egg) {
  if (!egg || typeof egg === 'string') return '';
  const heading = eggHeading(egg);
  if (egg.description && egg.description !== heading && egg.description !== egg.detail) {
    return egg.description;
  }
  return '';
}

function getSourceBadge(source) {
  switch (source) {
    case 'cdn':
      return <span className="badge green">⚡ Instant (Pre-cached)</span>;
    case 'api-cached':
      return <span className="badge blue">💾 Cached (Previously searched)</span>;
    case 'api-processing':
      return <span className="badge orange">🔄 Processing (Check back soon)</span>;
    default:
      return null;
  }
}

function placeholderFromTap(m) {
  return {
    id: m.id,
    title: m.title,
    year: m.year,
    posterPath: m.posterPath || m.poster_path || null,
    source: 'api-processing',
  };
}

window.MovieSearchComponent = function() {
  const [query, setQuery] = useState('');
  const [year, setYear] = useState('');
  const [chosen, setChosen] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [featuredMovies, setFeaturedMovies] = useState([]);
  const [recentSearches, setRecentSearches] = useState([]);
  const [activeTab, setActiveTab] = useState('home');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState('');
  const parsedYear = year ? parseInt(year, 10) : undefined;
  const { results, movie, loading, source, error } = window.useMovieSearch(
    query, parsedYear, chosen
  );
  const displayMovie = (movie && chosen && movie.id === chosen.id) ? movie : (chosen ? {
    id: chosen.id,
    title: chosen.title,
    year: chosen.year,
    posterPath: chosen.posterPath || chosen.poster_path || null,
    source: 'api-processing',
  } : null);
  const displaySource = (movie && chosen && movie.id === chosen.id && source) || (displayMovie && displayMovie.source) || source;

  const openMovie = (m) => {
    const placeholder = placeholderFromTap(m);
    setQuery(m.title || '');
    setYear(m.year ? m.year.toString() : '');
    setChosen(placeholder);
    setActiveTab('home');
  };

  const handleRefresh = async () => {
    if (!displayMovie || !displayMovie.id) return;
    setRefreshing(true);
    setRefreshMessage('');
    try {
      const response = await fetch(`${window.API_BASE}/movie/${displayMovie.id}/refresh`, {
        method: 'POST'
      });
      const data = await response.json();
      if (data.status === 'too_soon') {
        setRefreshMessage(data.message);
        setRefreshing(false);
      } else if (data.status === 'processing') {
        setRefreshMessage('🔄 Re-analyzing with TMDB keywords and Ollama...');
        setTimeout(() => {
          const next = { ...chosen, title: displayMovie.title, year: displayMovie.year, id: displayMovie.id };
          setChosen(null);
          setTimeout(() => setChosen(next), 100);
        }, 35000);
      }
    } catch (e) {
      setRefreshMessage('❌ Error refreshing. Please try again.');
      setRefreshing(false);
    }
  };

  useEffect(() => {
    window.preloadCDNData().then(() => {
      setLoaded(true);
      const theatersData = window.getTheatersData();
      if (theatersData && theatersData.movies) {
        const featured = theatersData.movies.filter(m => {
          const currentYear = new Date().getFullYear();
          return m.year >= currentYear - 1;
        });
        setFeaturedMovies(featured);
      }
      const onDemandData = window.getOnDemandData();
      if (onDemandData && onDemandData.movies) {
        const withContent = onDemandData.movies.filter(m =>
          (m.postCredits && m.postCredits.hasScene) ||
          (m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0)
        );
        setRecentSearches(withContent.slice(0, 20));
      }
    });
  }, []);

  if (!loaded) {
    return <div>Loading movie database...</div>;
  }

  const renderMovieCard = (m, showClickHint = false) => (
    <div
      key={m.id}
      className="movie-card"
      style={{ marginBottom: '16px', cursor: showClickHint ? 'pointer' : 'default', transition: 'transform 0.2s, box-shadow 0.2s' }}
      onClick={showClickHint ? () => openMovie(m) : undefined}
      onMouseOver={showClickHint ? (e) => {
        e.currentTarget.style.transform = 'scale(1.02)';
        e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.15)';
      } : undefined}
      onMouseOut={showClickHint ? (e) => {
        e.currentTarget.style.transform = 'scale(1)';
        e.currentTarget.style.boxShadow = 'none';
      } : undefined}
    >
      <h3 style={{ color: '#2d3748', fontSize: '1.3em', marginBottom: '12px' }}>
        {m.title} ({m.year})
        {showClickHint && <span style={{ marginLeft: '8px', fontSize: '0.7em', color: '#718096' }}>→ Click to view</span>}
      </h3>
      {m.posterPath && (
        <img src={posterSrc(m.posterPath)} alt={m.title} style={{ maxWidth: 200, marginBottom: '12px' }} />
      )}
      {m.postCredits && m.postCredits.hasScene && (
        <div style={{ marginBottom: '12px' }}>
          <span className="badge green">🎬 {m.postCredits.sceneCount} Post-Credit Scene{m.postCredits.sceneCount > 1 ? 's' : ''}</span>
          {isWorthStaying(m.postCredits.worthStaying) && (
            <div style={{ marginTop: '8px', color: '#d69e2e', fontWeight: '600' }}>
              ⭐ Worth staying for!
            </div>
          )}
          {m.postCredits.spoilerFreeHint && (
            <div style={{ marginTop: '8px', color: '#4a5568' }}>
              💡 {m.postCredits.spoilerFreeHint}
            </div>
          )}
        </div>
      )}
      {m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0 && (
        <div style={{ marginTop: '12px' }}>
          <span className="badge blue">🥚 {m.easterEggs.length} Easter Egg{m.easterEggs.length > 1 ? 's' : ''}</span>
          <ul style={{ marginTop: '12px', paddingLeft: '0' }}>
            {m.easterEggs.map((egg, idx) => (
              <li key={idx} style={{
                padding: '12px',
                margin: '8px 0',
                background: 'white',
                borderRadius: '8px',
                borderLeft: '4px solid #667eea',
                listStyle: 'none'
              }}>
                <strong style={{ color: '#2d3748' }}>{eggHeading(egg)}</strong>
                {eggBody(egg) && (
                  <div style={{ marginTop: '4px', color: '#4a5568', fontSize: '14px' }}>
                    {eggBody(egg)}
                  </div>
                )}
                {egg.significance && (
                  <div style={{ marginTop: '4px', color: '#718096', fontSize: '14px' }}>
                    {egg.significance}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.overview && (
        <p style={{ marginTop: '12px', color: '#4a5568', fontSize: '14px', lineHeight: '1.5' }}>
          {m.overview.length > 200 ? m.overview.substring(0, 200) + '...' : m.overview}
        </p>
      )}
    </div>
  );

  return (
    <div className="search-container">
      <h1>Movie Post-Credits & Easter Eggs</h1>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', borderBottom: '2px solid #e2e8f0' }}>
        <button
          onClick={() => {
            setActiveTab('home');
            setQuery('');
            setYear('');
            setChosen(null);
          }}
          style={{
            padding: '12px 24px',
            background: activeTab === 'home' ? '#667eea' : 'transparent',
            color: activeTab === 'home' ? 'white' : '#4a5568',
            border: 'none',
            borderBottom: activeTab === 'home' ? '3px solid #667eea' : '3px solid transparent',
            cursor: 'pointer',
            fontWeight: '600',
            fontSize: '16px',
            transition: 'all 0.2s'
          }}
        >
          🏠 Home
        </button>
        <button
          onClick={async () => {
            setActiveTab('recent');
            setQuery('');
            setYear('');
            setChosen(null);
            try {
              const cacheBuster = Date.now();
              const response = await fetch(`${window.CDN_BASE}on-demand-movies.json?v=${cacheBuster}`);
              const onDemandData = await response.json();
              const withContent = onDemandData.movies.filter(m =>
                (m.postCredits && m.postCredits.hasScene) ||
                (m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0)
              );
              setRecentSearches(withContent.slice(0, 20));
              console.log(`🔄 Refreshed recent searches: ${withContent.length} movies`);
            } catch (e) {
              console.warn('Failed to reload recent searches:', e);
            }
          }}
          style={{
            padding: '12px 24px',
            background: activeTab === 'recent' ? '#667eea' : 'transparent',
            color: activeTab === 'recent' ? 'white' : '#4a5568',
            border: 'none',
            borderBottom: activeTab === 'recent' ? '3px solid #667eea' : '3px solid transparent',
            cursor: 'pointer',
            fontWeight: '600',
            fontSize: '16px',
            transition: 'all 0.2s'
          }}
        >
          🕐 Recent Searches {recentSearches.length > 0 && `(${recentSearches.length})`}
        </button>
      </div>

      <div className="search-controls">
        <input
          type="text"
          value={query}
          onChange={e => {
            setQuery(e.target.value);
            setChosen(null);
          }}
          placeholder="Search for a movie..."
        />
        <input
          type="number"
          min="1900"
          max="2100"
          value={year}
          onChange={e => {
            setYear(e.target.value);
            setChosen(null);
          }}
          placeholder="Year (optional)"
        />
      </div>

      {error && <div className="error">{error}</div>}

      {query && !chosen && (
        <div>
          <h2 style={{ marginTop: '24px', marginBottom: '16px', color: '#2d3748' }}>
            Search results{results && results.length ? ` (${results.length})` : ''}
          </h2>
          {loading && <div>Searching...</div>}
          {!loading && results && results.length === 0 && String(query).trim() && (
            <div style={{ textAlign: 'center', padding: '24px', color: '#718096' }}>
              No movies found
            </div>
          )}
          {(results || []).map((m) => (
            <div
              key={m.id}
              className="movie-card"
              style={{ marginBottom: '12px', cursor: 'pointer', display: 'flex', gap: '16px', alignItems: 'flex-start', transition: 'transform 0.2s, box-shadow 0.2s' }}
              onClick={() => openMovie(m)}
              onMouseOver={(e) => {
                e.currentTarget.style.transform = 'scale(1.01)';
                e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.15)';
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.transform = 'scale(1)';
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              {m.posterPath && (
                <img src={posterSrc(m.posterPath)} alt={m.title} style={{ width: 80, height: 120, objectFit: 'cover', margin: 0, borderRadius: 8, flexShrink: 0 }} />
              )}
              <div>
                <h3 style={{ color: '#2d3748', fontSize: '1.1em', marginBottom: '8px' }}>
                  {m.title}{m.year ? ` (${m.year})` : ''}
                </h3>
                {m.overview && (
                  <p style={{ color: '#4a5568', fontSize: '14px', lineHeight: '1.5' }}>
                    {m.overview.length > 160 ? m.overview.substring(0, 160) + '...' : m.overview}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {!query && !chosen && activeTab === 'home' && (
        <div>
          {featuredMovies.length > 0 ? (
            <>
              <h2 style={{ marginTop: '24px', marginBottom: '16px', color: '#2d3748' }}>
                🎬 Now in Theaters ({featuredMovies.length})
              </h2>
              {featuredMovies.map(m => renderMovieCard(m, true))}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: '#718096' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🎬</div>
              <p style={{ fontSize: '18px', marginBottom: '8px' }}>No movies in theaters yet</p>
              <p style={{ fontSize: '14px' }}>Search for any movie to discover post-credits scenes and easter eggs!</p>
            </div>
          )}
        </div>
      )}

      {!query && !chosen && activeTab === 'recent' && (
        <div>
          <h2 style={{ marginTop: '24px', marginBottom: '16px', color: '#2d3748' }}>
            🕐 Recent Searches ({recentSearches.length})
          </h2>
          {recentSearches.length > 0 ? (
            <div>
              <p style={{ color: '#718096', fontSize: '14px', marginBottom: '16px' }}>
                Movies you've searched that have post-credits scenes or easter eggs
              </p>
              {recentSearches.map(m => renderMovieCard(m, true))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: '#718096' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔍</div>
              <p style={{ fontSize: '18px', marginBottom: '8px' }}>No recent searches yet</p>
              <p style={{ fontSize: '14px' }}>Search for movies to see them here</p>
            </div>
          )}
        </div>
      )}

      {chosen && displayMovie && (
        <div>
          <button
            onClick={() => {
              setChosen(null);
              setQuery('');
              setYear('');
            }}
            style={{
              marginBottom: '16px',
              padding: '8px 16px',
              background: '#f7fafc',
              color: '#4a5568',
              border: '2px solid #e2e8f0',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
            onMouseOver={(e) => {
              e.target.style.background = '#e2e8f0';
            }}
            onMouseOut={(e) => {
              e.target.style.background = '#f7fafc';
            }}
          >
            ← Back to {activeTab === 'recent' ? 'Recent Searches' : 'Home'}
          </button>

          <div className="movie-card">
            {getSourceBadge(displaySource)}
            <h2>
              {displayMovie.title} ({displayMovie.year})
            </h2>
            {displayMovie.posterPath && (
              <img src={posterSrc(displayMovie.posterPath)} alt={displayMovie.title} style={{ maxWidth: 240 }} />
            )}

            {displayMovie.source === 'api-processing' && (
              <div style={{ marginTop: '16px', padding: '20px', background: '#e6fffa', borderRadius: '8px', border: '2px solid #38b2ac', textAlign: 'center' }}>
                <div style={{ fontSize: '48px', marginBottom: '12px' }}>⏳</div>
                <h3 style={{ color: '#234e52', marginBottom: '12px' }}>Analyzing Movie...</h3>
                <p style={{ color: '#4a5568', marginBottom: '8px' }}>
                  🎬 Checking TMDB credit-scene keywords<br/>
                  🔎 Reading live articles, then Ollama extract<br/>
                  🥚 Saving post-credits info
                </p>
                <p style={{ color: '#718096', fontSize: '14px', marginTop: '16px' }}>
                  This page will automatically update in 30-60 seconds when complete.
                </p>
                <div style={{ marginTop: '12px', padding: '8px', background: '#f7fafc', borderRadius: '4px', fontSize: '12px', color: '#718096' }}>
                  Auto-refreshing every 30 seconds...
                </div>
              </div>
            )}

            {displayMovie.source !== 'api-processing' && displayMovie.postCredits && displayMovie.postCredits.confidence !== 'processing' ? (
              <div>
                {displayMovie.postCredits.hasScene ? (
                  <div>
                    <h3>🎬 Post-Credits Scenes</h3>
                    <p>Count: {displayMovie.postCredits.sceneCount}</p>
                    {isWorthStaying(displayMovie.postCredits.worthStaying) && (
                      <p className="highlight">⭐ Worth staying for!</p>
                    )}
                    {displayMovie.postCredits.spoilerFreeHint && (
                      <p>Hint: {displayMovie.postCredits.spoilerFreeHint}</p>
                    )}
                  </div>
                ) : (
                  <p>No post-credits scenes</p>
                )}
              </div>
            ) : displayMovie.source !== 'api-processing' ? (
              <p>No post-credits scenes</p>
            ) : null}

            {displayMovie.source !== 'api-processing' && displayMovie.easterEggs && Array.isArray(displayMovie.easterEggs) && displayMovie.easterEggs.length > 0 && (
              <div>
                <h3>🥚 Easter Eggs & Hidden Details</h3>
                <ul>
                  {displayMovie.easterEggs.map((egg, i) => (
                    <li key={i}>
                      <strong>{eggHeading(egg)}</strong>
                      {egg.significance && <span> — {egg.significance}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {displaySource === 'cdn' && displayMovie.tier && (
              <small>From: {displayMovie.tier} collection</small>
            )}

            {displayMovie.source !== 'api-processing' && (
              <div style={{ marginTop: '24px', paddingTop: '24px', borderTop: '2px solid #e2e8f0' }}>
                <button
                  onClick={handleRefresh}
                  disabled={refreshing}
                  style={{
                    padding: '12px 24px',
                    background: refreshing ? '#cbd5e0' : '#667eea',
                    color: 'white',
                    border: 'none',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: '600',
                    cursor: refreshing ? 'not-allowed' : 'pointer',
                    width: '100%',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => {
                    if (!refreshing) e.target.style.background = '#5568d3';
                  }}
                  onMouseOut={(e) => {
                    if (!refreshing) e.target.style.background = '#667eea';
                  }}
                >
                  {refreshing ? '🔄 Refreshing...' : '🔄 Re-analyze with Latest Data'}
                </button>
                {refreshMessage && (
                  <div style={{
                    marginTop: '12px',
                    padding: '12px',
                    background: refreshMessage.includes('❌') ? '#fff5f5' : '#e6fffa',
                    borderRadius: '8px',
                    fontSize: '14px',
                    color: '#4a5568',
                    textAlign: 'center'
                  }}>
                    {refreshMessage}
                  </div>
                )}
                <p style={{ marginTop: '8px', fontSize: '12px', color: '#718096', textAlign: 'center' }}>
                  Re-checks TMDB keywords + Ollama writeups (15 min cooldown)
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
