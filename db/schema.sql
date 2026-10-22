-- ==============================================================================
-- DocuSphere AI: Full Enterprise Relational SQLite Schema
-- Supports Company Organization Hierarchy, Multi-Format Documents,
-- Chat Sessions, Grounded Message Audits, and Verifiable Source Citations.
-- ==============================================================================

PRAGMA foreign_keys = ON;

-- 1. COMPANIES (Organizations)
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ticker_or_code TEXT,
    sector TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. DOCUMENTS (Multi-Format Files tagged by Company)
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_type TEXT NOT NULL,                  -- 'pdf', 'docx', 'xml', 'xbrl', 'html', 'txt'
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER DEFAULT 0,
    total_pages_or_sections INTEGER DEFAULT 1,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'indexed',            -- 'pending', 'indexed', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE CASCADE
);

-- 3. CHAT SESSIONS (Multi-turn Sessions with Company-Level Filters)
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    selected_company_ids TEXT DEFAULT '[]',   -- JSON array of company IDs filtered in this session
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. CHAT MESSAGES (Grounded RAG Dialogue with Confidence & Audit Logs)
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,                       -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    confidence TEXT,                          -- 'High', 'Medium', 'Low'
    reasoning TEXT,                           -- Verification logs / Agent self-correction feedback
    verification_attempts INTEGER DEFAULT 1,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id) ON DELETE CASCADE
);

-- 5. VERIFIABLE CITATIONS (Granular Source Proof per Assistant Message)
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    document_id INTEGER,
    company_name TEXT NOT NULL,
    document_name TEXT NOT NULL,
    page_or_section TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages (id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE SET NULL
);

-- ==============================================================================
-- PERFORMANCE INDEXES
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_citations_message ON citations(message_id);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
