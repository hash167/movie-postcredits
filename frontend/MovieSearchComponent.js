(() => {
  const { useState, useEffect } = React;
  function eggBody(egg) {
    const d = (egg && (egg.detail || egg.description || egg.title) || egg || "").toString().trim();
    const s = (egg && egg.significance || "").toString().trim();
    if (!s || /^(high|medium|low)$/i.test(s)) return d;
    if (d.includes(s)) return d;
    if (s.length > d.length) return s;
    return d || s;
  }

  function getSourceBadge(source) {
    switch (source) {
      case "cdn":
        return /* @__PURE__ */ React.createElement("span", { className: "badge green" }, "\u26A1 Instant (Pre-cached)");
      case "api-cached":
        return /* @__PURE__ */ React.createElement("span", { className: "badge blue" }, "\u{1F4BE} Cached (Previously searched)");
      case "api-processing":
        return /* @__PURE__ */ React.createElement("span", { className: "badge orange" }, "\u{1F504} Processing (Check back soon)");
      case "api-fresh":
        return /* @__PURE__ */ React.createElement("span", { className: "badge green" }, "Analyzed just now");
      default:
        return null;
    }
  }
  const RECENT_KEY = "movieRecentSearches";
  const RECENT_MAX = 20;
  function loadRecentSearches() {
    try {
      const raw = localStorage.getItem(RECENT_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }
  function toRecentItem(m) {
    return {
      id: m.id,
      title: m.title,
      year: m.year,
      posterPath: m.posterPath || m.poster_path || null,
      postCredits: m.postCredits || null,
      easterEggs: Array.isArray(m.easterEggs) ? m.easterEggs : []
    };
  }
  function saveRecentSearches(list) {
    const next = (list || []).slice(0, RECENT_MAX);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    } catch (e) {}
    return next;
  }
  function prependRecentSearch(list, movie) {
    if (!movie || movie.id == null) return list || [];
    const item = toRecentItem(movie);
    const rest = (list || []).filter((m) => m && m.id !== item.id);
    return saveRecentSearches([item].concat(rest));
  }
  function placeholderFromTap(m) {
    return {
      id: m.id,
      title: m.title,
      year: m.year,
      posterPath: m.posterPath || m.poster_path || null,
      source: "api-processing"
    };
  }
  window.MovieSearchComponent = function() {
    const [query, setQuery] = useState("");
    const [year, setYear] = useState("");
    const [chosen, setChosen] = useState(null);
    const [loaded, setLoaded] = useState(false);
    const [featuredMovies, setFeaturedMovies] = useState([]);
    const [recentSearches, setRecentSearches] = useState(() => loadRecentSearches());
    const [activeTab, setActiveTab] = useState("home");
    const [refreshing, setRefreshing] = useState(false);
    const [refreshMessage, setRefreshMessage] = useState("");
    const { results, movie, loading, source, error } = window.useMovieSearch(query, year ? parseInt(year) : void 0, chosen);
    const displayMovie = (movie && chosen && movie.id === chosen.id) ? movie : (chosen ? {
      id: chosen.id,
      title: chosen.title,
      year: chosen.year,
      posterPath: chosen.posterPath || chosen.poster_path || null,
      source: "api-processing"
    } : null);
    const displaySource = (movie && chosen && movie.id === chosen.id && source) || (displayMovie && displayMovie.source) || source;
    const handleRefresh = async () => {
      if (!movie || !movie.id) return;
      setRefreshing(true);
      setRefreshMessage("");
      try {
        const response = await fetch(`${window.API_BASE}/movie/${movie.id}/refresh`, {
          method: "POST"
        });
        const data = await response.json();
        if (data.status === "too_soon") {
          setRefreshMessage(data.message);
          setRefreshing(false);
        } else if (data.status === "processing") {
          setRefreshMessage("\u{1F504} Fetching live writeups and extracting with Ollama...");
          setTimeout(() => {
            setChosen(null);
            setTimeout(() => setChosen({ title: movie.title, year: movie.year, id: movie.id }), 100);
          }, 35e3);
        }
      } catch (e) {
        setRefreshMessage("\u274C Error refreshing. Please try again.");
        setRefreshing(false);
      }
    };
    useEffect(() => {
      window.preloadCDNData().then(() => {
        setLoaded(true);
        const theatersData = window.getTheatersData();
        if (theatersData && theatersData.movies) {
          const featured = theatersData.movies.filter((m) => {
            const currentYear = (/* @__PURE__ */ new Date()).getFullYear();
            return !m.year || m.year >= currentYear - 1;
          });
          setFeaturedMovies(featured);
        }
      });
    }, []);
    useEffect(() => {
      if (movie && movie.id != null) {
        setRecentSearches((prev) => prependRecentSearch(prev, movie));
      }
    }, [movie]);
    if (!loaded) {
      return /* @__PURE__ */ React.createElement("div", null, "Loading movie database...");
    }
    const renderMovieCard = (m, showClickHint = false) => /* @__PURE__ */ React.createElement(
      "div",
      {
        key: m.id,
        className: "movie-card",
        style: { marginBottom: "16px", cursor: showClickHint ? "pointer" : "default", transition: "transform 0.2s, box-shadow 0.2s" },
        onClick: showClickHint ? () => {
          const placeholder = placeholderFromTap(m);
          setRecentSearches((prev) => prependRecentSearch(prev, placeholder));
          setQuery(m.title);
          setYear(m.year ? m.year.toString() : "");
          setChosen(placeholder);
          setActiveTab("home");
        } : void 0,
        onMouseOver: showClickHint ? (e) => {
          e.currentTarget.style.transform = "scale(1.02)";
          e.currentTarget.style.boxShadow = "0 4px 20px rgba(0,0,0,0.15)";
        } : void 0,
        onMouseOut: showClickHint ? (e) => {
          e.currentTarget.style.transform = "scale(1)";
          e.currentTarget.style.boxShadow = "none";
        } : void 0
      },
      /* @__PURE__ */ React.createElement("h3", { style: { color: "#2d3748", fontSize: "1.3em", marginBottom: "12px" } }, m.title, " (", m.year, ")", showClickHint && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "8px", fontSize: "0.7em", color: "#718096" } }, "\u2192 Click to view")),
      m.posterPath && /* @__PURE__ */ React.createElement("img", { src: window.rewritePoster ? window.rewritePoster(m.posterPath) : m.posterPath, alt: m.title, style: { maxWidth: 200, marginBottom: "12px" } }),
      m.postCredits && m.postCredits.hasScene && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: "12px" } }, /* @__PURE__ */ React.createElement("span", { className: "badge green" }, "\u{1F3AC} ", m.postCredits.sceneCount, " Post-Credit Scene", m.postCredits.sceneCount > 1 ? "s" : ""), m.postCredits.worthStaying && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "8px", color: "#d69e2e", fontWeight: "600" } }, "\u2B50 Worth staying for!"), m.postCredits.spoilerFreeHint && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "8px", color: "#4a5568" } }, "\u{1F4A1} ", m.postCredits.spoilerFreeHint)),
      m.easterEggs && Array.isArray(m.easterEggs) && m.easterEggs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "12px" } }, /* @__PURE__ */ React.createElement("span", { className: "badge blue" }, "\u{1F95A} ", m.easterEggs.length, " Easter Egg", m.easterEggs.length > 1 ? "s" : ""), /* @__PURE__ */ React.createElement("ul", { style: { marginTop: "12px", paddingLeft: "0" } }, m.easterEggs.map((egg, idx) => /* @__PURE__ */ React.createElement("li", { key: idx, style: {
        padding: "12px",
        margin: "8px 0",
        background: "white",
        borderRadius: "8px",
        borderLeft: "4px solid #667eea",
        listStyle: "none"
      } }, /* @__PURE__ */ React.createElement("div", { style: { color: "#2d3748", lineHeight: "1.5", overflowWrap: "anywhere", whiteSpace: "normal" } }, eggBody(egg)))))),
      m.overview && /* @__PURE__ */ React.createElement("p", { style: { marginTop: "12px", color: "#4a5568", fontSize: "14px", lineHeight: "1.5" } }, m.overview.length > 200 ? m.overview.substring(0, 200) + "..." : m.overview)
    );
    return /* @__PURE__ */ React.createElement("div", { className: "search-container" }, /* @__PURE__ */ React.createElement("h1", null, "Movie Post-Credits & Easter Eggs"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: "8px", marginBottom: "24px", borderBottom: "2px solid #e2e8f0" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          setActiveTab("home");
          setQuery("");
          setYear("");
          setChosen(null);
        },
        style: {
          padding: "12px 24px",
          background: activeTab === "home" ? "#667eea" : "transparent",
          color: activeTab === "home" ? "white" : "#4a5568",
          border: "none",
          borderBottom: activeTab === "home" ? "3px solid #667eea" : "3px solid transparent",
          cursor: "pointer",
          fontWeight: "600",
          fontSize: "16px",
          transition: "all 0.2s"
        }
      },
      "\u{1F3E0} Home"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          setActiveTab("recent");
          setQuery("");
          setYear("");
          setChosen(null);
          setRecentSearches(loadRecentSearches());
        },
        style: {
          padding: "12px 24px",
          background: activeTab === "recent" ? "#667eea" : "transparent",
          color: activeTab === "recent" ? "white" : "#4a5568",
          border: "none",
          borderBottom: activeTab === "recent" ? "3px solid #667eea" : "3px solid transparent",
          cursor: "pointer",
          fontWeight: "600",
          fontSize: "16px",
          transition: "all 0.2s"
        }
      },
      "\u{1F550} Recent Searches ",
      recentSearches.length > 0 && `(${recentSearches.length})`
    )), /* @__PURE__ */ React.createElement("div", { className: "search-controls" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        value: query,
        onChange: (e) => {
          setQuery(e.target.value);
          setChosen(null);
        },
        placeholder: "Search for a movie..."
      }
    ), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        inputMode: "numeric",
        maxLength: 4,
        value: year,
        onChange: (e) => {
          setYear(String(e.target.value).replace(/\D/g, "").slice(0, 4));
          setChosen(null);
        },
        placeholder: "Year (optional)"
      }
    )), error && /* @__PURE__ */ React.createElement("div", { className: "error" }, error), query && !chosen && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h2", { style: { marginTop: "24px", marginBottom: "16px", color: "#2d3748" } }, "Search results", results && results.length ? " (" + results.length + ")" : ""), loading && /* @__PURE__ */ React.createElement("div", null, "Searching..."), !loading && results && results.length === 0 && String(query).trim() && /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", padding: "24px", color: "#718096" } }, "No movies found"), (results || []).map((m) => /* @__PURE__ */ React.createElement("div", {
      key: m.id,
      className: "movie-card",
      style: { marginBottom: "12px", cursor: "pointer", display: "flex", gap: "16px", alignItems: "flex-start", transition: "transform 0.2s, box-shadow 0.2s" },
      onClick: () => {
        const placeholder = placeholderFromTap(m);
        setRecentSearches((prev) => prependRecentSearch(prev, placeholder));
        setChosen(placeholder);
        if (m.year) setYear(String(m.year));
        setActiveTab("home");
      },
      onMouseOver: (e) => {
        e.currentTarget.style.transform = "scale(1.01)";
        e.currentTarget.style.boxShadow = "0 4px 20px rgba(0,0,0,0.15)";
      },
      onMouseOut: (e) => {
        e.currentTarget.style.transform = "scale(1)";
        e.currentTarget.style.boxShadow = "none";
      }
    }, m.posterPath && /* @__PURE__ */ React.createElement("img", { src: window.rewritePoster ? window.rewritePoster(m.posterPath) : m.posterPath, alt: m.title, style: { width: 80, height: 120, objectFit: "cover", margin: 0, borderRadius: 8, flexShrink: 0 } }), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", { style: { color: "#2d3748", fontSize: "1.1em", marginBottom: "8px" } }, m.title, m.year ? " (" + m.year + ")" : ""), m.overview && /* @__PURE__ */ React.createElement("p", { style: { color: "#4a5568", fontSize: "14px", lineHeight: "1.5" } }, m.overview.length > 160 ? m.overview.substring(0, 160) + "..." : m.overview))))), !query && !chosen && !movie && activeTab === "home" && /* @__PURE__ */ React.createElement("div", null, featuredMovies.length > 0 ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("h2", { style: { marginTop: "24px", marginBottom: "16px", color: "#2d3748" } }, "\u{1F3AC} Now in Theaters (", featuredMovies.length, ")"), featuredMovies.map((m) => renderMovieCard(m, true))) : /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", padding: "40px", color: "#718096" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "48px", marginBottom: "16px" } }, "\u{1F3AC}"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: "18px", marginBottom: "8px" } }, "No movies in theaters yet"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: "14px" } }, "Search for any movie to discover post-credits scenes and easter eggs!"))), !query && !chosen && !movie && activeTab === "recent" && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h2", { style: { marginTop: "24px", marginBottom: "16px", color: "#2d3748" } }, "\u{1F550} Recent Searches (", recentSearches.length, ")"), recentSearches.length > 0 ? /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("p", { style: { color: "#718096", fontSize: "14px", marginBottom: "16px" } }, "Movies you opened on this phone (saved in the browser only)"), recentSearches.map((m) => renderMovieCard(m, true))) : /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", padding: "40px", color: "#718096" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "48px", marginBottom: "16px" } }, "\u{1F50D}"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: "18px", marginBottom: "8px" } }, "No recent searches yet"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: "14px" } }, "Search for movies to see them here"))), chosen && !displayMovie && loading && /* @__PURE__ */ React.createElement("div", null, "Searching..."), chosen && displayMovie && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          setChosen(null);
          setQuery("");
          setYear("");
        },
        style: {
          marginBottom: "16px",
          padding: "8px 16px",
          background: "#f7fafc",
          color: "#4a5568",
          border: "2px solid #e2e8f0",
          borderRadius: "8px",
          cursor: "pointer",
          fontWeight: "600",
          fontSize: "14px",
          transition: "all 0.2s"
        },
        onMouseOver: (e) => {
          e.target.style.background = "#e2e8f0";
        },
        onMouseOut: (e) => {
          e.target.style.background = "#f7fafc";
        }
      },
      "\u2190 Back to ",
      activeTab === "recent" ? "Recent Searches" : "Home"
    ), /* @__PURE__ */ React.createElement("div", { className: "movie-card" }, getSourceBadge(displaySource), /* @__PURE__ */ React.createElement("h2", null, displayMovie.title, " (", displayMovie.year, ")"), displayMovie.posterPath && /* @__PURE__ */ React.createElement("img", { src: window.rewritePoster ? window.rewritePoster(displayMovie.posterPath) : displayMovie.posterPath, alt: displayMovie.title, style: { maxWidth: 240 } }), displayMovie.source === "api-processing" && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "16px", padding: "20px", background: "#e6fffa", borderRadius: "8px", border: "2px solid #38b2ac", textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "48px", marginBottom: "12px" } }, "\u23F3"), /* @__PURE__ */ React.createElement("h3", { style: { color: "#234e52", marginBottom: "12px" } }, "Analyzing Movie..."), /* @__PURE__ */ React.createElement("p", { style: { color: "#4a5568", marginBottom: "8px" } }, "\u{1F50D} Fetching live writeups", /* @__PURE__ */ React.createElement("br", null), "\u{1F916} Extracting with Ollama", /* @__PURE__ */ React.createElement("br", null), "\u{1F95A} Finding easter eggs & post-credits info"), /* @__PURE__ */ React.createElement("p", { style: { color: "#718096", fontSize: "14px", marginTop: "16px" } }, "This page will automatically update in 30-60 seconds when complete."), /* @__PURE__ */ React.createElement("div", { style: { marginTop: "12px", padding: "8px", background: "#f7fafc", borderRadius: "4px", fontSize: "12px", color: "#718096" } }, "Auto-refreshing every 30 seconds...")), displayMovie.source !== "api-processing" && displayMovie.postCredits && displayMovie.postCredits.confidence !== "processing" ? /* @__PURE__ */ React.createElement("div", null, displayMovie.postCredits.hasScene ? /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", null, "\u{1F3AC} Post-Credits Scenes"), /* @__PURE__ */ React.createElement("p", null, "Count: ", displayMovie.postCredits.sceneCount), displayMovie.postCredits.worthStaying && /* @__PURE__ */ React.createElement("p", { className: "highlight" }, "\u2B50 Worth staying for!"), displayMovie.postCredits.spoilerFreeHint && /* @__PURE__ */ React.createElement("p", null, "Hint: ", displayMovie.postCredits.spoilerFreeHint)) : /* @__PURE__ */ React.createElement("p", null, "No post-credits scenes")) : displayMovie.source !== "api-processing" ? /* @__PURE__ */ React.createElement("p", null, "No post-credits scenes") : null, displayMovie.source !== "api-processing" && displayMovie.easterEggs && Array.isArray(displayMovie.easterEggs) && displayMovie.easterEggs.length > 0 && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", null, "\u{1F95A} Easter Eggs & Hidden Details"), /* @__PURE__ */ React.createElement("ul", null, displayMovie.easterEggs.map((egg, i) => /* @__PURE__ */ React.createElement("li", { key: i, style: { overflowWrap: "anywhere", whiteSpace: "normal" } }, /* @__PURE__ */ React.createElement("div", { style: { color: "#2d3748", lineHeight: "1.5" } }, eggBody(egg)))))), displaySource === "cdn" && displayMovie.tier && /* @__PURE__ */ React.createElement("small", null, "From: ", displayMovie.tier, " collection"), displayMovie.source !== "api-processing" && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "24px", paddingTop: "24px", borderTop: "2px solid #e2e8f0" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: handleRefresh,
        disabled: refreshing,
        style: {
          padding: "12px 24px",
          background: refreshing ? "#cbd5e0" : "#667eea",
          color: "white",
          border: "none",
          borderRadius: "8px",
          fontSize: "14px",
          fontWeight: "600",
          cursor: refreshing ? "not-allowed" : "pointer",
          width: "100%",
          transition: "all 0.2s"
        },
        onMouseOver: (e) => {
          if (!refreshing) e.target.style.background = "#5568d3";
        },
        onMouseOut: (e) => {
          if (!refreshing) e.target.style.background = "#667eea";
        }
      },
      refreshing ? "\u{1F504} Refreshing..." : "\u{1F504} Re-analyze with Latest Data"
    ), refreshMessage && /* @__PURE__ */ React.createElement("div", { style: {
      marginTop: "12px",
      padding: "12px",
      background: refreshMessage.includes("\u274C") ? "#fff5f5" : "#e6fffa",
      borderRadius: "8px",
      fontSize: "14px",
      color: "#4a5568",
      textAlign: "center"
    } }, refreshMessage), /* @__PURE__ */ React.createElement("p", { style: { marginTop: "8px", fontSize: "12px", color: "#718096", textAlign: "center" } }, "Fetches live writeups and extracts easter eggs with Ollama")))));
  };
})();
