// Same-origin template. The published frontend/config.js matches this.
// The browser talks only to the page origin; nginx proxies API and MinIO.
window.CDN_BASE = window.location.origin + '/';
window.API_BASE = window.location.origin;
