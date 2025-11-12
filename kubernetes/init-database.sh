#!/bin/bash

# Initialize PostgreSQL database schema in Kubernetes
# Run this script to create all required tables

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Initialize Database Schema${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Check if postgres pod exists
if ! kubectl get pod -n movie-api -l app=postgres &> /dev/null; then
    echo -e "${RED}Error: PostgreSQL pod not found${NC}"
    echo "Make sure PostgreSQL is deployed first"
    exit 1
fi

POD_NAME=$(kubectl get pod -n movie-api -l app=postgres -o jsonpath='{.items[0].metadata.name}')

echo -e "${YELLOW}PostgreSQL pod: ${GREEN}$POD_NAME${NC}"
echo ""

echo -e "${YELLOW}Creating database schema...${NC}"

# Create tables using heredoc
kubectl exec -i $POD_NAME -n movie-api -- psql -U movieuser -d moviedb <<'EOF'
-- Drop existing tables if they exist (for clean setup)
DROP TABLE IF EXISTS easter_eggs CASCADE;
DROP TABLE IF EXISTS reddit_insights CASCADE;
DROP TABLE IF EXISTS post_credits CASCADE;
DROP TABLE IF EXISTS movies CASCADE;

-- Movies table (main table)
CREATE TABLE movies (
    id INTEGER PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    release_date DATE,
    runtime_minutes INTEGER,
    poster_path VARCHAR(500),
    overview TEXT,
    vote_average DECIMAL(3,1),
    popularity DECIMAL(10,3),
    imdb_id VARCHAR(20),
    tier VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Post-credits scenes table
CREATE TABLE post_credits (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    has_scene BOOLEAN DEFAULT FALSE,
    scene_count INTEGER DEFAULT 0,
    mid_credits TEXT,
    post_credits TEXT,
    worth_staying VARCHAR(50),
    spoiler_free_hint TEXT,
    source_confidence VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(movie_id)
);

-- Easter eggs table
CREATE TABLE easter_eggs (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    title VARCHAR(500),
    description TEXT,
    timestamp_minutes INTEGER,
    significance VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reddit insights table
CREATE TABLE reddit_insights (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    reddit_discussion_count INTEGER DEFAULT 0,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(movie_id)
);

-- Create indexes for better performance
CREATE INDEX idx_movies_title ON movies(title);
CREATE INDEX idx_movies_year ON movies(year);
CREATE INDEX idx_movies_tier ON movies(tier);
CREATE INDEX idx_post_credits_movie_id ON post_credits(movie_id);
CREATE INDEX idx_easter_eggs_movie_id ON easter_eggs(movie_id);
CREATE INDEX idx_reddit_insights_movie_id ON reddit_insights(movie_id);

-- Verify tables were created
\dt

-- Show table counts
SELECT 'movies' as table_name, COUNT(*) as count FROM movies
UNION ALL
SELECT 'post_credits', COUNT(*) FROM post_credits
UNION ALL
SELECT 'easter_eggs', COUNT(*) FROM easter_eggs
UNION ALL
SELECT 'reddit_insights', COUNT(*) FROM reddit_insights;

EOF

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}======================================${NC}"
    echo -e "${GREEN}✓ Database schema created successfully!${NC}"
    echo -e "${GREEN}======================================${NC}"
    echo ""
    echo -e "${YELLOW}Tables created:${NC}"
    echo "  - movies"
    echo "  - post_credits"
    echo "  - easter_eggs"
    echo "  - reddit_insights"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Restart your API pods:"
    echo -e "     ${GREEN}kubectl rollout restart deployment/movie-api -n movie-api${NC}"
    echo ""
    echo "  2. Check API logs:"
    echo -e "     ${GREEN}kubectl logs -f deployment/movie-api -n movie-api${NC}"
    echo ""
    echo "  3. Test the API:"
    echo -e "     ${GREEN}curl http://localhost:30800/health${NC}"
    echo ""
else
    echo ""
    echo -e "${RED}❌ Failed to create schema${NC}"
    echo "Check PostgreSQL logs:"
    echo -e "  ${GREEN}kubectl logs $POD_NAME -n movie-api${NC}"
    exit 1
fi

