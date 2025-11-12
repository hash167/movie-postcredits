# Quick Start Guide

Get up and running in 5 minutes!

## 🚀 One-Command Setup

```bash
bash scripts/setup_local_dev.sh
```

That's it! This will:
- ✅ Start PostgreSQL and MinIO
- ✅ Create virtual environment
- ✅ Install dependencies
- ✅ Create `.env` template

## 📝 Configuration

Edit `.env` and add your API keys:

```bash
nano .env
```

Required:
```bash
OPENAI_API_KEY=sk-your-key
TMDB_API_KEY=your-key
```

Already configured for local MinIO:
```bash
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=movies
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
```

## 🎮 Common Commands

### Start Services
```bash
docker-compose up -d
```

### Activate Environment
```bash
source venv/bin/activate
```

### Export & Upload Data
```bash
# Process movies in theaters
python -m src.run_batch --mode theaters --export --upload

# Just export and upload existing data
python -m src.run_batch --export-only --upload
```

### Start API Server
```bash
uvicorn src.api:app --reload
```

### Start Frontend
```bash
cd frontend
python -m http.server 8080
```

## 🌐 Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| MinIO API | http://localhost:9000 | - |
| PostgreSQL | localhost:5432 | movieuser / moviepass |
| API Server | http://localhost:8000 | - |
| API Docs | http://localhost:8000/docs | - |
| Frontend | http://localhost:8080 | - |

## 📦 File Access

View uploaded files:
```bash
# Via browser
open http://localhost:9000/movies/theaters-movies.json

# Via curl
curl http://localhost:9000/movies/theaters-movies.json

# Via console
open http://localhost:9001
```

## 🔄 Development Workflow

```bash
# 1. Start services
docker-compose up -d

# 2. Activate environment
source venv/bin/activate

# 3. Make changes to code
# ... edit files ...

# 4. Test your changes
python -m src.run_batch --mode theaters --export --upload

# 5. Check results in MinIO
open http://localhost:9001

# 6. Test API
uvicorn src.api:app --reload

# 7. Test frontend
cd frontend && python -m http.server 8080
```

## 🧹 Cleanup

### Stop Services
```bash
docker-compose down
```

### Reset All Data
```bash
docker-compose down -v
docker-compose up -d
```

## 🆘 Troubleshooting

### Services Won't Start
```bash
docker-compose down
docker-compose up -d
docker ps  # Check status
```

### Check Logs
```bash
docker logs moviedb    # PostgreSQL
docker logs minio      # MinIO
```

### Port Conflicts
Change ports in `docker-compose.yml` if 5432, 9000, or 9001 are in use.

### Bucket Issues
```bash
# Manually create bucket
docker exec -it minio mc mb /data/movies
docker exec -it minio mc anonymous set download /data/movies
```

## 🚢 Deploy to Production

When ready for production, you can:

1. **Option A:** Deploy MinIO to a server/cloud
2. **Option B:** Use any S3-compatible service (AWS S3, etc.)

Update `.env` with production credentials:
```bash
S3_ENDPOINT=https://your-s3-endpoint.com
S3_BUCKET=your-bucket
S3_ACCESS_KEY=your-key
S3_SECRET_KEY=your-secret
S3_PUBLIC_URL=https://your-cdn-url.com  # Optional CDN
```

Run upload:
```bash
python -m src.run_batch --export-only --upload
```

## 📚 Documentation

- **Local Development:** [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)
- **Full Documentation:** [README.md](README.md)

## 💡 Pro Tips

### View All Files in MinIO
```bash
curl http://localhost:9000/movies/ | grep -o '<Key>[^<]*</Key>'
```

### Pretty Print JSON
```bash
curl http://localhost:9000/movies/theaters-movies.json | jq
```

### Quick Status Check
```bash
docker ps && echo "" && curl -s http://localhost:9000/minio/health/live && echo "MinIO: OK"
```

### Watch Logs
```bash
docker-compose logs -f
```

## ⚡ Speed Tips

### Skip Delays
Edit `src/storage_uploader.py` and reduce:
```python
await asyncio.sleep(0.5)  # Change to 0.1 or 0
```

### Parallel Processing
Process multiple tiers at once:
```bash
python -m src.run_batch --mode theaters --export --upload &
python -m src.run_batch --mode popular --export --upload &
wait
```

## 🎯 Next Steps

1. ✅ Run setup script
2. ✅ Add API keys to `.env`
3. ✅ Test upload to MinIO
4. ✅ View files in console
5. ✅ Start API server
6. ✅ Test frontend

You're ready to develop! 🎉

---

**Questions?** Check [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for detailed instructions.

