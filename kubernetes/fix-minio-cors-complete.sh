#!/bin/bash

# Complete MinIO CORS Fix for Remote Access
# This script properly configures MinIO CORS for browser access

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Fix MinIO CORS for Remote Access${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Get MinIO pod
POD_NAME=$(kubectl get pod -n movie-api -l app=minio -o jsonpath='{.items[0].metadata.name}')

echo -e "${YELLOW}MinIO pod: ${GREEN}$POD_NAME${NC}"
echo ""

echo -e "${YELLOW}Step 1: Creating CORS policy file...${NC}"

# Create CORS policy on local machine
cat > /tmp/minio-cors.json <<'EOF'
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "HEAD", "PUT", "POST"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag", "Content-Length", "Content-Type", "x-amz-request-id", "x-amz-id-2"],
      "MaxAgeSeconds": 3600
    }
  ]
}
EOF

echo -e "${GREEN}✓ CORS policy created${NC}"
echo ""

echo -e "${YELLOW}Step 2: Copying CORS policy to MinIO pod...${NC}"
kubectl cp /tmp/minio-cors.json movie-api/$POD_NAME:/tmp/cors.json

echo -e "${GREEN}✓ Policy copied${NC}"
echo ""

echo -e "${YELLOW}Step 3: Applying CORS configuration...${NC}"

kubectl exec $POD_NAME -n movie-api -- sh -c '
# Setup alias
mc alias set myminio http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD

# Apply CORS
mc anonymous set-json /tmp/cors.json myminio/movies

# Set public read access
mc anonymous set download myminio/movies

# Show configuration
echo ""
echo "=== Current CORS Configuration ==="
mc anonymous get-json myminio/movies

echo ""
echo "=== Bucket Policy ==="
mc anonymous get myminio/movies
'

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}======================================${NC}"
    echo -e "${GREEN}✓ CORS Configured Successfully!${NC}"
    echo -e "${GREEN}======================================${NC}"
    echo ""
    echo -e "${YELLOW}Testing CORS...${NC}"
    
    # Test CORS
    echo ""
    curl -I -H "Origin: http://localhost:8080" \
         -H "Access-Control-Request-Method: GET" \
         http://100.67.63.33:30900/movies/ 2>&1 | grep -i "access-control"
    
    echo ""
    echo -e "${YELLOW}If you see 'Access-Control-Allow-Origin', CORS is working!${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "1. Clear browser cache (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows)"
    echo "2. Reload http://localhost:8080"
    echo "3. Check browser console for CORS errors"
    echo ""
else
    echo -e "${RED}❌ Failed to configure CORS${NC}"
    exit 1
fi

