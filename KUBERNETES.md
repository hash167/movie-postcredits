# Kubernetes Deployment Guide

Complete guide for deploying the Movie Post-Credits API on Kubernetes with a 2-server cluster.

---

## Table of Contents

1. [Quick Start (3 Steps)](#quick-start-3-steps)
2. [Cluster Setup](#cluster-setup)
3. [Deploy Application](#deploy-application)
4. [Scheduled Batch Jobs](#scheduled-batch-jobs)
5. [Monitoring & Management](#monitoring--management)
6. [Troubleshooting](#troubleshooting)
7. [Cleanup & Reset](#cleanup--reset)

---

## Quick Start (3 Steps)

### Already Have a Kubernetes Cluster?

```bash
# 1. Create storage directories (on master node)
sudo mkdir -p /mnt/data/{postgres,minio}
sudo chmod -R 777 /mnt/data

# 2. Deploy everything
kubectl apply -f kubernetes/all-in-one.yaml

# 3. Initialize database
bash kubernetes/init-database.sh

# 4. Deploy CronJob for theater movies
kubectl apply -f kubernetes/cronjobs.yaml
```

**Access your API:**
```bash
# Get node IP
NODE_IP=$(kubectl get nodes -o wide | awk 'NR==2 {print $6}')

# Test API
curl http://$NODE_IP:30800/health

# Access MinIO console
echo "MinIO Console: http://$NODE_IP:30900"
```

---

## Cluster Setup

### Step 1: Prepare Servers (Both Nodes)

Run on **BOTH** master and worker nodes:

```bash
# Run the automated setup script
cd movie-postcredits
sudo bash kubernetes/setup-k8s-node.sh
```

This installs:
- containerd (container runtime)
- kubectl, kubeadm, kubelet
- Configures networking

**Time:** ~5 minutes per server

---

### Step 2: Initialize Master Node

Run on **Server 1** (Master) only:

```bash
# Replace with your master's IP address
sudo bash kubernetes/init-master.sh 192.168.1.10
```

**Save the join command** from the output! It looks like:
```bash
kubeadm join 192.168.1.10:6443 --token abc123... --discovery-token-ca-cert-hash sha256:...
```

**Time:** ~5 minutes

---

### Step 3: Join Worker Node

Run on **Server 2** (Worker) only:

```bash
# Set hostname
sudo hostnamectl set-hostname k8s-worker1

# Run the join command from Step 2
sudo kubeadm join 192.168.1.10:6443 --token abc123... --discovery-token-ca-cert-hash sha256:...
```

**Time:** ~2 minutes

---

### Step 4: Verify Cluster

On master node:

```bash
kubectl get nodes

# Expected output:
# NAME          STATUS   ROLES           AGE   VERSION
# k8s-master    Ready    control-plane   10m   v1.28.x
# k8s-worker1   Ready    <none>          5m    v1.28.x
```

✅ **Cluster is ready!**

---

## Deploy Application

### What Gets Deployed

- **PostgreSQL** - Database for movie data
- **MinIO** - S3-compatible object storage
- **FastAPI** - Your application (2 replicas)
- **Auto-scaling** - Scales 2-10 pods based on load

### Deploy

```bash
# 1. Create storage directories (on master node)
sudo mkdir -p /mnt/data/postgres
sudo mkdir -p /mnt/data/minio
sudo chmod -R 777 /mnt/data

# 2. Deploy all services
kubectl apply -f kubernetes/all-in-one.yaml

# 3. Watch pods start
kubectl get pods -n movie-api -w

# Wait for all pods to show "Running" (2-3 minutes)
```

### Initialize Database Schema

```bash
# Create database tables
bash kubernetes/init-database.sh

# Verify tables exist
kubectl exec -it deployment/postgres -n movie-api -- \
  psql -U movieuser -d moviedb -c "\dt"
```

### Verify Deployment

```bash
# Check all resources
kubectl get all -n movie-api

# Test API
NODE_IP=$(kubectl get nodes -o wide | awk 'NR==2 {print $6}')
curl http://$NODE_IP:30800/health
curl http://$NODE_IP:30800/stats
```

**Services Available:**
- API: `http://<NODE_IP>:30800`
- MinIO Console: `http://<NODE_IP>:30900`
- MinIO API: `http://<NODE_IP>:30901`

---

## Scheduled Batch Jobs

### Deploy CronJob

```bash
# Deploy daily theater movies update
kubectl apply -f kubernetes/cronjobs.yaml

# Verify
kubectl get cronjobs -n movie-api
```

**Schedule:** Runs daily at 2:00 AM UTC

### Test Immediately

```bash
# Trigger the job now (don't wait for schedule)
kubectl create job --from=cronjob/theaters-daily theaters-test-$(date +%s) -n movie-api

# Watch it run
kubectl get jobs -n movie-api -w

# View logs
kubectl logs -l app=movie-batch,tier=theaters -n movie-api --tail=100 -f
```

### Customize Schedule

Edit `kubernetes/cronjobs.yaml` line 29:

```yaml
# Current: Daily at 2 AM
schedule: "0 2 * * *"

# Every 6 hours
schedule: "0 */6 * * *"

# Twice daily (8 AM and 8 PM)
schedule: "0 8,20 * * *"
```

Then reapply:
```bash
kubectl apply -f kubernetes/cronjobs.yaml
```

---

## Monitoring & Management

### View Logs

```bash
# API logs
kubectl logs -f deployment/movie-api -n movie-api

# PostgreSQL logs
kubectl logs -f deployment/postgres -n movie-api

# MinIO logs
kubectl logs -f deployment/minio -n movie-api

# CronJob logs
kubectl logs -l app=movie-batch,tier=theaters -n movie-api --tail=100
```

### Access Services

```bash
# PostgreSQL shell
kubectl exec -it deployment/postgres -n movie-api -- \
  psql -U movieuser -d moviedb

# MinIO shell
kubectl exec -it deployment/minio -n movie-api -- sh

# API shell
kubectl exec -it deployment/movie-api -n movie-api -- bash
```

### Scale Application

```bash
# Manual scaling
kubectl scale deployment movie-api --replicas=5 -n movie-api

# Check auto-scaling status
kubectl get hpa -n movie-api

# View metrics
kubectl top nodes
kubectl top pods -n movie-api
```

### Update Application

```bash
# After building new Docker image
kubectl set image deployment/movie-api api=randomnumber20/movie-api:latest -n movie-api

# Or restart deployment
kubectl rollout restart deployment/movie-api -n movie-api

# Check rollout status
kubectl rollout status deployment/movie-api -n movie-api
```

### Backup Database

```bash
# Backup
kubectl exec deployment/postgres -n movie-api -- \
  pg_dump -U movieuser moviedb > backup-$(date +%Y%m%d).sql

# Restore
cat backup.sql | kubectl exec -i deployment/postgres -n movie-api -- \
  psql -U movieuser moviedb
```

### Pause/Resume CronJob

```bash
# Pause
kubectl patch cronjob theaters-daily -n movie-api -p '{"spec":{"suspend":true}}'

# Resume
kubectl patch cronjob theaters-daily -n movie-api -p '{"spec":{"suspend":false}}'
```

---

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n movie-api

# Check events
kubectl get events -n movie-api --sort-by='.lastTimestamp'

# Common issues:
# - PV not bound: Check /mnt/data directories exist
# - Image pull error: Check Docker image name
# - CrashLoopBackOff: Check logs
```

### Storage Issues

```bash
# Check PV/PVC
kubectl get pv,pvc -n movie-api

# If PVC is Pending:
sudo mkdir -p /mnt/data/{postgres,minio}
sudo chmod -R 777 /mnt/data

# Delete and recreate
kubectl delete pvc postgres-pvc minio-pvc -n movie-api
kubectl apply -f kubernetes/all-in-one.yaml
```

### Database Connection Errors

```bash
# Test database
kubectl exec -it deployment/postgres -n movie-api -- \
  psql -U movieuser -d moviedb -c "SELECT 1;"

# Check service
kubectl get svc postgres -n movie-api

# Restart API
kubectl rollout restart deployment/movie-api -n movie-api
```

### CORS Issues (Frontend)

```bash
# Fix MinIO CORS
bash kubernetes/fix-minio-cors-complete.sh

# Or deploy proxy (avoids CORS entirely)
kubectl apply -f kubernetes/api-with-minio-proxy.yaml

# Then update frontend to use:
# CDN_BASE = 'http://<NODE_IP>:30901/cdn/'
```

### CronJob Not Running

```bash
# Check if suspended
kubectl get cronjob theaters-daily -n movie-api

# Check schedule
kubectl describe cronjob theaters-daily -n movie-api

# Check for failed jobs
kubectl get jobs -n movie-api

# View job logs
kubectl logs job/<job-name> -n movie-api
```

### Batch Job Finds No Movies

This was fixed in the code. If you still see this:

```bash
# Rebuild Docker image with fix
docker buildx build --no-cache --platform linux/amd64 -t randomnumber20/movie-api:latest --push .

# Restart deployment
kubectl rollout restart deployment/movie-api -n movie-api

# Test job
kubectl create job --from=cronjob/theaters-daily test-now -n movie-api
kubectl logs -l app=movie-batch,tier=theaters -n movie-api --tail=100 -f
```

---

## Cleanup & Reset

### Remove Application

```bash
# Delete all resources
kubectl delete namespace movie-api

# Clean up persistent volumes
kubectl delete pv postgres-pv minio-pv
```

### Reset Kubernetes Node

Run on each node:

```bash
# Automated cleanup
sudo bash kubernetes/reset-k8s.sh
sudo reboot
```

Or manually:

```bash
# On master
kubectl drain k8s-worker1 --delete-emptydir-data --force --ignore-daemonsets
kubectl delete node k8s-worker1

# On worker
sudo kubeadm reset -f
sudo rm -rf /etc/kubernetes /var/lib/kubelet /var/lib/etcd $HOME/.kube

# On both nodes
sudo reboot
```

---

## Configuration Reference

### Key Files

| File | Purpose |
|------|---------|
| `kubernetes/all-in-one.yaml` | Complete application stack |
| `kubernetes/cronjobs.yaml` | Scheduled batch processing |
| `kubernetes/setup-k8s-node.sh` | Automated node setup |
| `kubernetes/init-master.sh` | Automated master initialization |
| `kubernetes/init-database.sh` | Database schema creation |
| `kubernetes/reset-k8s.sh` | Complete cleanup |

### Service Ports

| Service | Internal Port | External NodePort |
|---------|---------------|-------------------|
| API | 8000 | 30800 |
| MinIO Console | 9001 | 30900 |
| MinIO API | 9000 | 30901 |
| PostgreSQL | 5432 | (internal only) |

### Environment Variables

Configured in `kubernetes/all-in-one.yaml`:

```yaml
# Database (line 67)
DATABASE_URL: postgresql://movieuser:<POSTGRES_PASSWORD>@postgres:5432/moviedb

# API Keys (lines 70-71)
OPENAI_API_KEY: "your-key-here"
TMDB_API_KEY: "your-key-here"

# MinIO (lines 74-78)
S3_ENDPOINT: http://minio:9000
S3_BUCKET: movies
S3_ACCESS_KEY: <MINIO_ROOT_USER>
S3_SECRET_KEY: <MINIO_ROOT_PASSWORD>
```

---

## Quick Commands Reference

```bash
# Deployment
kubectl apply -f kubernetes/all-in-one.yaml
kubectl apply -f kubernetes/cronjobs.yaml
bash kubernetes/init-database.sh

# Monitoring
kubectl get all -n movie-api
kubectl logs -f deployment/movie-api -n movie-api
kubectl top nodes
kubectl top pods -n movie-api

# Management
kubectl rollout restart deployment/movie-api -n movie-api
kubectl scale deployment movie-api --replicas=5 -n movie-api
kubectl exec -it deployment/postgres -n movie-api -- psql -U movieuser -d moviedb

# CronJobs
kubectl get cronjobs -n movie-api
kubectl create job --from=cronjob/theaters-daily test-now -n movie-api
kubectl logs -l app=movie-batch,tier=theaters -n movie-api

# Cleanup
kubectl delete namespace movie-api
sudo bash kubernetes/reset-k8s.sh
```

---

## Architecture

```
┌─────────────────────────────────────┐
│         External Access             │
│  - API: NodePort 30800              │
│  - MinIO Console: NodePort 30900    │
│  - MinIO API: NodePort 30901        │
└───────────────┬─────────────────────┘
                │
┌───────────────▼─────────────────────┐
│       Kubernetes Cluster            │
│                                     │
│  ┌──────────┐  ┌──────────┐       │
│  │ Master   │  │ Worker   │       │
│  │ Node     │  │ Node     │       │
│  └──────────┘  └──────────┘       │
│                                     │
│  ┌────────────────────────────┐   │
│  │  FastAPI Pods (2-10)       │   │
│  │  - Auto-scaling            │   │
│  │  - Load balanced           │   │
│  └────────────────────────────┘   │
│             ↓                      │
│  ┌──────────┼──────────┐          │
│  │          ↓          │          │
│  │  ┌──────────┐  ┌───────┐      │
│  │  │PostgreSQL│  │ MinIO │      │
│  │  └──────────┘  └───────┘      │
│  │       ↓              ↓         │
│  │  /mnt/data/   /mnt/data/      │
│  │   postgres      minio         │
│  └────────────────────────────────┘
│                                     │
│  ┌────────────────────────────────┐│
│  │  CronJob (Daily 2 AM)         ││
│  │  - Fetch theater movies       ││
│  │  - Process with Reddit/AI     ││
│  │  - Export to JSON            ││
│  │  - Upload to MinIO           ││
│  └────────────────────────────────┘│
└─────────────────────────────────────┘
```

---

## Next Steps

1. ✅ **Cluster Setup** - Follow [Cluster Setup](#cluster-setup)
2. ✅ **Deploy Application** - Follow [Deploy Application](#deploy-application)
3. ✅ **Initialize Database** - Run `bash kubernetes/init-database.sh`
4. ✅ **Deploy CronJob** - Run `kubectl apply -f kubernetes/cronjobs.yaml`
5. ✅ **Test Everything** - Try the API and trigger a batch job
6. 🔧 **Fix CORS** (if accessing from browser) - Run `bash kubernetes/fix-minio-cors-complete.sh`
7. 📊 **Monitor** - Set up external monitoring (UptimeRobot, etc.)
8. 💾 **Backups** - Set up automated database backups
9. 🔒 **Security** - Update passwords in `all-in-one.yaml`
10. 🚀 **Production** - Consider managed PostgreSQL and S3 for scale

---

**Total Setup Time: ~30 minutes for complete cluster + application deployment**

**Need help?** Check the [Troubleshooting](#troubleshooting) section or review command outputs for errors.

