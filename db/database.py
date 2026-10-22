import sqlite3
import os
import logging
from contextlib import contextmanager
from config import Config

logger = logging.getLogger(__name__)

def get_raw_connection() -> sqlite3.Connection:
    """Establishes an optimized SQLite connection with dict-like row access."""
    conn = sqlite3.connect(Config.DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # Enforce SQLite foreign keys and WAL mode for high concurrent throughput
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db_connection():
    """Context manager for automatic commit and rollback of SQLite transactions."""
    conn = get_raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction error: {e}")
        raise e
    finally:
        conn.close()

def _migrate_schema_columns(conn: sqlite3.Connection):
    """Automatically adds missing columns to existing tables for backwards compatibility."""
    cursor = conn.cursor()
    
    # 1. chat_sessions columns migration
    cursor.execute("PRAGMA table_info(chat_sessions);")
    session_cols = {row['name'] for row in cursor.fetchall()}
    if session_cols:
        if 'updated_at' not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN updated_at TIMESTAMP;")
            cursor.execute("UPDATE chat_sessions SET updated_at = created_at WHERE updated_at IS NULL;")
            logger.info("Migrated chat_sessions: added updated_at column.")
        if 'selected_company_ids' not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN selected_company_ids TEXT DEFAULT '[]';")
            logger.info("Migrated chat_sessions: added selected_company_ids column.")

    # 2. chat_messages columns migration
    cursor.execute("PRAGMA table_info(chat_messages);")
    msg_cols = {row['name'] for row in cursor.fetchall()}
    if msg_cols:
        if 'confidence' not in msg_cols:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN confidence TEXT;")
            logger.info("Migrated chat_messages: added confidence column.")
        if 'reasoning' not in msg_cols:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN reasoning TEXT;")
            logger.info("Migrated chat_messages: added reasoning column.")
        if 'verification_attempts' not in msg_cols:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN verification_attempts INTEGER DEFAULT 1;")
            logger.info("Migrated chat_messages: added verification_attempts column.")

def init_db():
    """Initializes database tables, runs column migrations, and creates indexes."""
    schema_path = os.path.join(Config.BASE_DIR, "db", "schema.sql")
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Schema definition file not found at {schema_path}")
        
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        
    with get_db_connection() as conn:
        conn.executescript(schema_sql)
        _migrate_schema_columns(conn)
        logger.info(f"Initialized database schema successfully at: {Config.DB_PATH}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialization and migration completed successfully.")
