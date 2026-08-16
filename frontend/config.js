// Same-origin config so phones (no Tailscale / extra NodePorts) work.
// Nginx proxies /search /stats /health /movie/ /movies/tier/ to the API,
// /movies/ to MinIO, and /tmdb-image/ to image.tmdb.org.
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
