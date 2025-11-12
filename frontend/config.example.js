// Storage Configuration Template
// 
// Copy this file to config.js and update with your values:
// cp frontend/config.example.js frontend/config.js

// LOCAL DEVELOPMENT (MinIO):
window.CDN_BASE = 'http://localhost:9000/movies/';
window.API_BASE = 'http://localhost:8000';

// KUBERNETES DEPLOYMENT:
// Update with your actual node IP or Tailscale IP
// window.CDN_BASE = 'http://YOUR_NODE_IP:30901/movies/';
// window.API_BASE = 'http://YOUR_NODE_IP:30800';

// PRODUCTION (Update with your S3-compatible storage URL):
// window.CDN_BASE = 'https://your-cdn-url.com/movies/';
// window.API_BASE = 'https://your-api.com';

