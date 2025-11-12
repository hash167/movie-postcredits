const { useState, useEffect } = React;

const cdnDataCache = {
  theaters: null,
  popular: null,
  recent: null,
  'on-demand': null,
};

window.preloadCDNData = async function() {
  const tiers = ['theaters', 'popular', 'recent', 'on-demand'];
  const cacheBuster = Date.now(); // Force reload by adding timestamp
  await Promise.all(
    tiers.map(async (tier) => {
      try {
        const response = await fetch(`${window.CDN_BASE}${tier}-movies.json?v=${cacheBuster}`);
        const data = await response.json();
        cdnDataCache[tier] = data;
        console.log(`✅ Loaded ${tier}: ${data.movieCount} movies`);
        // Log easter eggs count for debugging
        const eggsCount = data.movies ? data.movies.filter(m => m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0).length : 0;
        console.log(`   📊 Movies with easter eggs: ${eggsCount}`);
      } catch (e) {
        console.warn(`Failed to load ${tier} from CDN:`, e);
      }
    })
  );
};

// Helper for searching CDN data
function searchInCDN(movieTitle, year) {
  const term = movieTitle.toLowerCase().trim();
  for (const tier of ['theaters', 'popular', 'recent', 'on-demand']) {
    const data = cdnDataCache[tier];
    if (!data || !data.movies) continue;
    const found = data.movies.find(movie => {
      const titleMatch =
        movie.title.toLowerCase().includes(term) ||
        term.includes(movie.title.toLowerCase());
      const yearMatch =
        !year || movie.year === year ||
        Math.abs(movie.year - year) <= 1; // Fuzzy match
      return titleMatch && yearMatch;
    });
    if (found) return { movie: found, tier };
  }
  return null;
}

window.useMovieSearch = function(movieTitle, year) {
  const [movie, setMovie] = useState(null);
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    if (!movieTitle) return;
    setLoading(true);
    setError(null);
    setPollCount(0);

    async function search() {
      // Step 1: CDN search
      const cdnResult = searchInCDN(movieTitle, year);
      if (cdnResult) {
        setMovie({ ...cdnResult.movie, source: 'cdn', tier: cdnResult.tier, instant: true });
        setSource('cdn');
        setLoading(false);
        return;
      }

      // Step 2: API fallback
      try {
        const response = await fetch(`${window.API_BASE}/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: movieTitle, year }),
        });
        const data = await response.json();
        setMovie({ ...data, source: data.cached ? 'api-cached' : 'api-processing', instant: false });
        setSource(data.cached ? 'api-cached' : 'api-processing');
        setLoading(false);

        // If processing, start auto-polling
        if (!data.cached) {
          startAutoPolling(data.id);
        }
      } catch (e) {
        setError(e.message || 'API error');
        setLoading(false);
      }
    }

    search();
    // eslint-disable-next-line
  }, [movieTitle, year]);

  function startAutoPolling(movieId) {
    let pollAttempts = 0;
    const maxPolls = 20; // Poll for up to 10 minutes (20 * 30s)
    
    const pollInterval = setInterval(async () => {
      pollAttempts++;
      console.log(`🔄 Auto-polling attempt ${pollAttempts}/${maxPolls}...`);
      
      try {
        const response = await fetch(`${window.API_BASE}/movie/${movieId}`);
        if (response.ok) {
          const data = await response.json();
          
          // Check if movie has been processed (has post-credits or easter eggs)
          const hasPostCredits = data.postCredits && data.postCredits.hasScene !== undefined;
          const hasEasterEggs = data.easterEggs && Array.isArray(data.easterEggs) && data.easterEggs.length > 0;
          
          if (hasPostCredits || hasEasterEggs || pollAttempts >= maxPolls) {
            console.log('✅ Processing complete! Updating movie data...');
            setMovie({ ...data, source: 'api-cached' });
            setSource('api-cached');
            clearInterval(pollInterval);
            
            // Show success message and reload on-demand cache
            if (hasPostCredits || hasEasterEggs) {
              console.log('🎉 Movie analysis complete!');
              // Reload on-demand tier to get updated recent searches
              setTimeout(async () => {
                try {
                  const cacheBuster = Date.now();
                  const response = await fetch(`${window.CDN_BASE}on-demand-movies.json?v=${cacheBuster}`);
                  const onDemandData = await response.json();
                  cdnDataCache['on-demand'] = onDemandData;
                  console.log('🔄 Reloaded on-demand movies from MinIO');
                } catch (e) {
                  console.warn('Failed to reload on-demand:', e);
                }
              }, 2000); // Wait 2s for export to complete
            }
          }
        }
      } catch (e) {
        console.error('Polling error:', e);
        if (pollAttempts >= maxPolls) {
          clearInterval(pollInterval);
        }
      }
    }, 30000); // Poll every 30 seconds
    
    // Clean up on component unmount
    return () => clearInterval(pollInterval);
  }

  return { movie, loading, source, error, pollCount };
};

// Helper function to get theaters data
window.getTheatersData = function() {
  return cdnDataCache['theaters'];
};

// Helper function to get on-demand data (for recent searches)
window.getOnDemandData = function() {
  return cdnDataCache['on-demand'];
};
