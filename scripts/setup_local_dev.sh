#!/bin/bash

# Local Development Setup Script
# Sets up MinIO and PostgreSQL for local development

set -e

echo "=================================="
echo "Local Development Setup"
echo "=================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "✓ Docker is running"

# Start services
echo ""
echo "${YELLOW}Starting PostgreSQL and MinIO...${NC}"
docker-compose up -d

# Wait for services to be healthy
echo ""
echo "${YELLOW}Waiting for services to be ready...${NC}"
sleep 5

# Check PostgreSQL
if docker exec moviedb pg_isready -U movieuser > /dev/null 2>&1; then
    echo "${GREEN}✓${NC} PostgreSQL is ready"
else
    echo "⚠️  PostgreSQL is starting (may take a moment)..."
fi

# Check MinIO
if curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "${GREEN}✓${NC} MinIO is ready"
else
    echo "⚠️  MinIO is starting (may take a moment)..."
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo "${YELLOW}Creating .env file for local development...${NC}"
    cat > .env << 'EOF'
# API Keys (Add your keys here)
TMDB_API_KEY=your-tmdb-api-key
OLLAMA_HOST=http://100.67.63.33:11434
OLLAMA_MODEL=llama3.1:8b

# Database (local PostgreSQL)
DATABASE_URL=postgresql://movieuser:moviepass@localhost:5432/moviedb

# S3-Compatible Storage (MinIO)
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=movies
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_REGION=us-east-1
S3_PUBLIC_URL=

# Export Directory
EXPORT_DIR=./exports
EOF
    echo "${GREEN}✓${NC} Created .env file"
    echo "${YELLOW}⚠️  Please edit .env and add your TMDB_API_KEY${NC}"
else
    echo ""
    echo "ℹ️  .env file already exists (skipping creation)"
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo ""
    echo "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
    echo "${GREEN}✓${NC} Virtual environment created"
fi

# Activate virtual environment and install dependencies
echo ""
echo "${YELLOW}Installing Python dependencies...${NC}"
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "${GREEN}✓${NC} Dependencies installed"

# Create exports directory
mkdir -p exports
echo "${GREEN}✓${NC} Exports directory ready"

echo ""
echo "=================================="
echo "${GREEN}Setup Complete!${NC}"
echo "=================================="
echo ""
echo "Services running:"
echo "  • PostgreSQL:    http://localhost:5432"
echo "  • MinIO API:     http://localhost:9000"
echo "  • MinIO Console: http://localhost:9001"
echo "    Login: minioadmin / minioadmin"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit .env and add your API keys:"
echo "   ${YELLOW}nano .env${NC}"
echo ""
echo "2. Activate the virtual environment:"
echo "   ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "3. Test the setup:"
echo "   ${YELLOW}python -m src.run_batch --export-only --upload${NC}"
echo ""
echo "4. Start the API server:"
echo "   ${YELLOW}uvicorn src.api:app --reload${NC}"
echo ""
echo "5. Open MinIO Console to see uploaded files:"
echo "   ${YELLOW}open http://localhost:9001${NC}"
echo ""
echo "For more details, see LOCAL_DEVELOPMENT.md"
echo ""

