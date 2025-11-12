-- Database setup for Movie Post-Credits & Easter Eggs

-- Create movies table
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    release_date VARCHAR(50),
    runtime_minutes INTEGER DEFAULT 0,
    poster_path TEXT,
    overview TEXT,
    vote_average DECIMAL(3, 1),
    popularity DECIMAL(10, 3),
    tier VARCHAR(50),
    imdb_id VARCHAR(20),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create post_credits table
CREATE TABLE IF NOT EXISTS post_credits (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE UNIQUE,
    has_scene BOOLEAN DEFAULT FALSE,
    scene_count INTEGER DEFAULT 0,
    mid_credits TEXT,
    post_credits TEXT,
    worth_staying BOOLEAN,
    spoiler_free_hint TEXT,
    source_confidence VARCHAR(50) DEFAULT 'medium'
);

-- Create easter_eggs table
CREATE TABLE IF NOT EXISTS easter_eggs (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE,
    detail TEXT NOT NULL,
    significance TEXT,
    confidence VARCHAR(50),
    source_url TEXT
);

-- Create reddit_insights table
CREATE TABLE IF NOT EXISTS reddit_insights (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE UNIQUE,
    discussion_count INTEGER DEFAULT 0,
    source_urls TEXT[],
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create batch_logs table
CREATE TABLE IF NOT EXISTS batch_logs (
    id SERIAL PRIMARY KEY,
    tier VARCHAR(50),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    movies_processed INTEGER DEFAULT 0,
    movies_failed INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running'
);

-- Create view for complete movie data
CREATE OR REPLACE VIEW movies_complete AS
SELECT 
    m.id,
    m.title,
    m.year,
    m.release_date,
    m.runtime_minutes,
    m.poster_path,
    m.overview,
    m.vote_average,
    m.popularity,
    m.tier,
    m.imdb_id,
    m.updated_at,
    pc.has_scene,
    pc.scene_count,
    pc.mid_credits,
    pc.post_credits as post_credits_desc,
    pc.worth_staying,
    pc.spoiler_free_hint,
    pc.source_confidence,
    ri.discussion_count as reddit_discussion_count,
    ri.source_urls as reddit_source_urls,
    ri.scraped_at as reddit_scraped_at,
    (SELECT json_agg(json_build_object(
        'detail', ee.detail,
        'significance', ee.significance,
        'confidence', ee.confidence,
        'source_url', ee.source_url
    )) FROM easter_eggs ee WHERE ee.movie_id = m.id) as easter_eggs
FROM movies m
LEFT JOIN post_credits pc ON m.id = pc.movie_id
LEFT JOIN reddit_insights ri ON m.id = ri.movie_id;

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_movies_id ON movies(id);
CREATE INDEX IF NOT EXISTS idx_movies_tier ON movies(tier);
CREATE INDEX IF NOT EXISTS idx_movies_popularity ON movies(popularity DESC);
CREATE INDEX IF NOT EXISTS idx_post_credits_movie_id ON post_credits(movie_id);
CREATE INDEX IF NOT EXISTS idx_easter_eggs_movie_id ON easter_eggs(movie_id);
CREATE INDEX IF NOT EXISTS idx_reddit_insights_movie_id ON reddit_insights(movie_id);
CREATE INDEX IF NOT EXISTS idx_batch_logs_tier ON batch_logs(tier);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for updated_at
CREATE TRIGGER update_movies_updated_at BEFORE UPDATE ON movies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

