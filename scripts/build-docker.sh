#!/bin/bash

# Build Docker image for Linux platform
# This script builds multi-platform images that work on Linux servers
#
# Usage: bash scripts/build-docker.sh [tag]
# Example: bash scripts/build-docker.sh latest

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Docker Multi-Platform Build${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Get Docker Hub username
read -p "Docker Hub username (default: randomnumber20): " DOCKER_USER
DOCKER_USER=${DOCKER_USER:-randomnumber20}

# Get image name
read -p "Image name (default: movie-api): " IMAGE_NAME
IMAGE_NAME=${IMAGE_NAME:-movie-api}

# Get tag
TAG=${1:-latest}

FULL_IMAGE="$DOCKER_USER/$IMAGE_NAME:$TAG"

echo ""
echo -e "${YELLOW}Building image: ${GREEN}$FULL_IMAGE${NC}"
echo -e "${YELLOW}Platform: ${GREEN}linux/amd64${NC}"
echo ""

# Check if buildx is available
if ! docker buildx version &> /dev/null; then
    echo -e "${RED}Error: docker buildx not found${NC}"
    echo "Please update Docker Desktop to the latest version"
    exit 1
fi

# Create builder if doesn't exist
if ! docker buildx inspect multiplatform &> /dev/null; then
    echo -e "${YELLOW}Creating buildx builder...${NC}"
    docker buildx create --name multiplatform --use
    docker buildx inspect --bootstrap
fi

# Use the multiplatform builder
docker buildx use multiplatform

echo -e "\n${YELLOW}Building Docker image for Linux (amd64)...${NC}"

# Build for linux/amd64 (most common for servers)
docker buildx build \
    --platform linux/amd64 \
    -t $FULL_IMAGE \
    --load \
    .

echo ""
echo -e "${GREEN}✓ Build complete!${NC}"
echo ""
echo -e "${YELLOW}Image details:${NC}"
docker images $FULL_IMAGE

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Test locally:"
echo -e "   ${GREEN}docker run --rm $FULL_IMAGE python --version${NC}"
echo ""
echo -e "2. Push to Docker Hub:"
echo -e "   ${GREEN}docker push $FULL_IMAGE${NC}"
echo ""
echo -e "3. Update Kubernetes deployment:"
echo -e "   ${GREEN}image: $FULL_IMAGE${NC}"
echo ""

