// Same-origin: phone only talks to :30801
window.CDN_BASE = window.location.origin + '/';
window.API_BASE = window.location.origin;

// Rewrite TMDB poster URLs through the nginx proxy when possible
window.rewritePoster = function(url) {
  if (!url) return url;
  var origin = window.location.origin;
  if (url.indexOf('https://image.tmdb.org/') === 0) {
    return origin + '/tmdb-image/' + url.substring('https://image.tmdb.org/'.length);
  }
  if (url.indexOf('http://image.tmdb.org/') === 0) {
    return origin + '/tmdb-image/' + url.substring('http://image.tmdb.org/'.length);
  }
  // MinIO / old CDN hosts -> same-origin /movies/ or path
  var m = url.match(/:30901(\/movies\/.*)$/);
  if (m) return origin + m[1];
  m = url.match(/\/movies\/(.+)$/);
  if (m && url.indexOf(origin) !== 0 && url.indexOf('http') === 0) {
    return origin + '/movies/' + m[1];
  }
  return url;
};
