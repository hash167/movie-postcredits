#!/bin/bash

# Build and Push Docker image for Linux in one step
# This is the fastest way to build and deploy
#
# Usage: bash scripts/build-and-push.sh [tag]
# Example: bash scripts/build-and-push.sh v1.0.0

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Build & Push Docker Image${NC}"
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
echo -e "${YELLOW}Building and pushing: ${GREEN}$FULL_IMAGE${NC}"
echo -e "${YELLOW}Platform: ${GREEN}linux/amd64${NC}"
echo ""

# Check if logged in
if ! docker info | grep -q "Username"; then
    echo -e "${YELLOW}Not logged in to Docker Hub. Logging in...${NC}"
    docker login
fi

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

echo -e "\n${YELLOW}Building and pushing Docker image...${NC}"
echo -e "${YELLOW}This may take a few minutes...${NC}"
echo ""

# Build and push in one step (faster than separate build + push)
docker buildx build \
    --platform linux/amd64 \
    -t $FULL_IMAGE \
    --push \
    .

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}✓ Build and push complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${YELLOW}Image pushed to Docker Hub:${NC}"
echo -e "  ${GREEN}$FULL_IMAGE${NC}"
echo ""
echo -e "${YELLOW}To deploy to Kubernetes:${NC}"
echo -e "  ${GREEN}kubectl set image deployment/movie-api api=$FULL_IMAGE -n movie-api${NC}"
echo ""
echo -e "${YELLOW}Or update all-in-one.yaml:${NC}"
echo -e "  Line 141: ${GREEN}image: $FULL_IMAGE${NC}"
echo ""

