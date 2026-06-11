CREATE TABLE IF NOT EXISTS doujinshi (
    nhentai_id INTEGER PRIMARY KEY,
    title_ja TEXT,
    title_en TEXT,
    title_pretty TEXT,
    media_id TEXT NOT NULL,
    cover_type TEXT DEFAULT 'j',
    pages INTEGER DEFAULT 0,
    uploaded_at INTEGER,
    favorited_at INTEGER,
    rating INTEGER,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS doujinshi_tags (
    doujinshi_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (doujinshi_id, tag_id),
    FOREIGN KEY (doujinshi_id) REFERENCES doujinshi(nhentai_id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);

CREATE INDEX IF NOT EXISTS idx_tags_type ON tags(type);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_doujinshi_rating ON doujinshi(rating);
CREATE INDEX IF NOT EXISTS idx_doujinshi_favorited ON doujinshi(favorited_at);
CREATE INDEX IF NOT EXISTS idx_doujinshi_uploaded ON doujinshi(uploaded_at);
