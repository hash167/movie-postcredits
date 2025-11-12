# Frontend Setup

## Quick Setup

### 1. Copy Config Template

```bash
cp frontend/config.example.js frontend/config.js
```

### 2. Update Config

Edit `frontend/config.js` with your values:

```javascript
// For local development
window.CDN_BASE = 'http://localhost:9000/movies/';
window.API_BASE = 'http://localhost:8000';

// For Kubernetes deployment
window.CDN_BASE = 'http://YOUR_NODE_IP:30901/movies/';
window.API_BASE = 'http://YOUR_NODE_IP:30800';

// For production
window.CDN_BASE = 'https://cdn.yourdomain.com/movies/';
window.API_BASE = 'https://api.yourdomain.com';
```

### 3. Serve Frontend

```bash
cd frontend

# Option 1: Python
python3 -m http.server 8080

# Option 2: Node.js
npx serve -p 8080

# Option 3: PHP
php -S localhost:8080
```

Access at: http://localhost:8080

---

## Configuration Options

### Local Development

```javascript
window.CDN_BASE = 'http://localhost:9000/movies/';
window.API_BASE = 'http://localhost:8000';
```

### Kubernetes (via Tailscale)

```javascript
window.CDN_BASE = 'http://100.x.x.x:30901/movies/';
window.API_BASE = 'http://100.x.x.x:30800';
```

### Kubernetes (Public IP)

```javascript
window.CDN_BASE = 'http://YOUR_PUBLIC_IP:30901/movies/';
window.API_BASE = 'http://YOUR_PUBLIC_IP:30800';
```

### Production (with Domain)

```javascript
window.CDN_BASE = 'https://cdn.yourdomain.com/movies/';
window.API_BASE = 'https://api.yourdomain.com';
```

---

## Troubleshooting

### Config Not Loading

**Error:** "Config not loaded! Make sure config.js exists."

**Solution:**
```bash
# Check if config.js exists
ls frontend/config.js

# If not, copy template
cp frontend/config.example.js frontend/config.js
```

### CORS Errors

**Error:** "Access blocked by CORS policy"

**Solution:**
```bash
# Fix MinIO CORS
bash kubernetes/fix-minio-cors-complete.sh

# Or update API CORS_ORIGINS
kubectl edit configmap movie-api-config -n movie-api
# Add your origin to CORS_ORIGINS
```

### Can't Access API

**Error:** "Failed to fetch"

**Solutions:**

1. **Check API is running:**
   ```bash
   curl http://YOUR_NODE_IP:30800/health
   ```

2. **Check NodePort:**
   ```bash
   kubectl get svc movie-api -n movie-api
   # Verify nodePort is 30800
   ```

3. **Update config.js with correct IP:**
   ```bash
   kubectl get nodes -o wide
   # Use INTERNAL-IP or EXTERNAL-IP
   ```

---

## Files

- `index.html` - Main HTML (safe to commit, no secrets)
- `config.js` - Your configuration (gitignored, not committed)
- `config.example.js` - Template (safe to commit)
- `*.js` - React components (safe to commit)

---

**Your frontend is now clean and ready for GitHub!** ✨

