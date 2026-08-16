// Same-origin config (copy to config.js if needed).
// Nginx proxies API, MinIO JSON, and TMDB images on this origin.
window.API_BASE = window.location.origin;
window.CDN_BASE = window.location.origin + '/movies/';

window.rewritePoster = function (url) {
  if (!url) return url;
  var prefixes = [
    'https://image.tmdb.org/',
    'http://image.tmdb.org/',
  ];
  for (var i = 0; i < prefixes.length; i++) {
    if (url.indexOf(prefixes[i]) === 0) {
      return window.location.origin + '/tmdb-image/' + url.slice(prefixes[i].length);
    }
  }
  return url;
};

// LOCAL DEVELOPMENT without nginx (API + MinIO on other ports):
// window.CDN_BASE = 'http://localhost:9000/movies/';
// window.API_BASE = 'http://localhost:8000';
