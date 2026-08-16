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

window.MovieSearchComponent = function() {
  const [query, setQuery] = useState('');
  const [year, setYear] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [featuredMovies, setFeaturedMovies] = useState([]);
  const [recentSearches, setRecentSearches] = useState([]);
  const [activeTab, setActiveTab] = useState('home');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState('');
  const { movie, loading, source, error } = window.useMovieSearch(query, year ? parseInt(year) : undefined);

  const handleRefresh = async () => {
    if (!movie || !movie.id) return;
    
    setRefreshing(true);
    setRefreshMessage('');
    
    try {
      const response = await fetch(`${window.API_BASE}/movie/${movie.id}/refresh`, {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.status === 'too_soon') {
        setRefreshMessage(data.message);
        setRefreshing(false);
      } else if (data.status === 'processing') {
        setRefreshMessage('🔄 Re-analyzing with fresh Reddit & IMDb data...');
        // Start polling
        setTimeout(() => {
          setQuery('');
          setTimeout(() => setQuery(movie.title), 100);
        }, 35000); // Refresh after 35 seconds
      }
    } catch (e) {
      setRefreshMessage('❌ Error refreshing. Please try again.');
      setRefreshing(false);
    }
  };

  useEffect(() => {
    window.preloadCDNData().then(() => {
      setLoaded(true);
      
      // Show all recent theater movies (eggs optional)
      const theatersData = window.getTheatersData();
      if (theatersData && theatersData.movies) {
        const featured = theatersData.movies.filter(m => {
          const currentYear = new Date().getFullYear();
          return m.year >= currentYear - 1;
        });
        setFeaturedMovies(featured);
      }
      
      // Get recent searches from on-demand tier (last 20 movies searched with content)
      const onDemandData = window.getOnDemandData();
      if (onDemandData && onDemandData.movies) {
        const withContent = onDemandData.movies.filter(m => 
          (m.postCredits && m.postCredits.hasScene) || 
          (m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0)
        );
        // Take last 20, most recent first
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
      onClick={showClickHint ? () => { 
        setQuery(m.title); 
        setYear(m.year ? m.year.toString() : ''); 
        setActiveTab('home'); 
      } : undefined}
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
      
      {/* Tab Navigation */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', borderBottom: '2px solid #e2e8f0' }}>
        <button
          onClick={() => {
            setActiveTab('home');
            setQuery('');
            setYear('');
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
            // Reload on-demand data when clicking Recent Searches
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
          onChange={e => setQuery(e.target.value)}
          placeholder="Search for a movie..."
        />
        <input
          type="number"
          min="1900"
          max="2100"
          value={year}
          onChange={e => setYear(e.target.value)}
          placeholder="Year (optional)"
        />
      </div>

      {loading && <div>Searching...</div>}
      {error && <div className="error">{error}</div>}

      {/* Home Tab: Show featured movies when not searching */}
      {!query && !movie && activeTab === 'home' && (
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

      {/* Recent Searches Tab */}
      {!query && !movie && activeTab === 'recent' && (
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

      {movie && (
        <div>
          {/* Back button */}
          <button
            onClick={() => {
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
            {getSourceBadge(source)}
            <h2>
              {movie.title} ({movie.year})
            </h2>
          {movie.posterPath && (
            <img src={posterSrc(movie.posterPath)} alt={movie.title} style={{ maxWidth: 240 }} />
          )}

          {/* Show processing state if analyzing */}
          {movie.source === 'api-processing' && (
            <div style={{ marginTop: '16px', padding: '20px', background: '#e6fffa', borderRadius: '8px', border: '2px solid #38b2ac', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '12px' }}>⏳</div>
              <h3 style={{ color: '#234e52', marginBottom: '12px' }}>Analyzing Movie...</h3>
              <p style={{ color: '#4a5568', marginBottom: '8px' }}>
                🔍 Scraping Reddit discussions<br/>
                🤖 Analyzing with AI<br/>
                🥚 Extracting easter eggs & post-credits info
              </p>
              <p style={{ color: '#718096', fontSize: '14px', marginTop: '16px' }}>
                This page will automatically update in 30-60 seconds when complete.
              </p>
              <div style={{ marginTop: '12px', padding: '8px', background: '#f7fafc', borderRadius: '4px', fontSize: '12px', color: '#718096' }}>
                Auto-refreshing every 30 seconds...
              </div>
            </div>
          )}

          {/* Post-credits info */}
          {movie.source !== 'api-processing' && movie.postCredits && movie.postCredits.confidence !== 'processing' ? (
            <div>
              {movie.postCredits.hasScene ? (
                <div>
                  <h3>🎬 Post-Credits Scenes</h3>
                  <p>Count: {movie.postCredits.sceneCount}</p>
                  {isWorthStaying(movie.postCredits.worthStaying) && (
                    <p className="highlight">⭐ Worth staying for!</p>
                  )}
                  {movie.postCredits.spoilerFreeHint && (
                    <p>Hint: {movie.postCredits.spoilerFreeHint}</p>
                  )}
                </div>
              ) : (
                <p>No post-credits scenes</p>
              )}
            </div>
          ) : movie.source !== 'api-processing' ? (
            <p>No post-credits scenes</p>
          ) : null}

          {/* Easter eggs */}
          {movie.source !== 'api-processing' && movie.easterEggs && Array.isArray(movie.easterEggs) && movie.easterEggs.length > 0 && (
            <div>
              <h3>🥚 Easter Eggs & Hidden Details</h3>
              <ul>
                {movie.easterEggs.map((egg, i) => (
                  <li key={i}>
                    <strong>{eggHeading(egg)}</strong>
                    {egg.significance && <span> — {egg.significance}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Source & tier */}
          {source === 'cdn' && movie.tier && (
            <small>From: {movie.tier} collection</small>
          )}
          
          {/* Refresh button for cached movies */}
          {movie.source !== 'api-processing' && (
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
                Re-scrapes Reddit + IMDb for fresh easter eggs (15 min cooldown)
              </p>
            </div>
          )}
          </div>
        </div>
      )}
    </div>
  );
};
