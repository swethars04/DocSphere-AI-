import sqlite3
import json
import os
import logging
from config import Config

logger = logging.getLogger(__name__)

def get_db_connection():
    """Establishes and returns a SQLite connection with dict-like row factory."""
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes database tables if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Reports Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            company_name TEXT,
            reporting_period TEXT,
            document_type TEXT,
            esg_summary TEXT,
            company_profile TEXT,
            predefined_prompts TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Chat Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            report_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
        )
    """)
    
    # 3. Chat Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            references_json TEXT,
            confidence_score REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id) ON DELETE CASCADE
        )
    """)
    
    # Migration checks for reports table columns
    cursor.execute("PRAGMA table_info(reports)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'predefined_prompts' not in columns:
        logger.info("Migrating database: Adding predefined_prompts column to reports table.")
        cursor.execute("ALTER TABLE reports ADD COLUMN predefined_prompts TEXT")
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")
    preload_default_report()

def add_report(filename, original_name, file_path, company_name, reporting_period, document_type, esg_summary, company_profile, predefined_prompts=None):
    """Inserts a new report record and returns its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (filename, original_name, file_path, company_name, reporting_period, document_type, esg_summary, company_profile, predefined_prompts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (filename, original_name, file_path, company_name, reporting_period, document_type, esg_summary, company_profile, predefined_prompts))
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id

def update_report_esg(report_id, esg_summary, company_profile, predefined_prompts=None):
    """Updates the ESG Summary, Company Profile, and Predefined Prompts of a report."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports
        SET esg_summary = ?, company_profile = ?, predefined_prompts = ?
        WHERE id = ?
    """, (esg_summary, company_profile, predefined_prompts, report_id))
    conn.commit()
    conn.close()

def get_reports():
    """Retrieves all uploaded reports."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY upload_date DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def find_report_by_company(company_name):
    """Searches for a registered report matching the company name (case-insensitive)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE LOWER(company_name) LIKE ? LIMIT 1", (f"%{company_name.lower()}%",))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_report(report_id):
    """Retrieves a single report by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_report(report_id):
    """Deletes a report, corresponding vector indices, and associated DB records."""
    report = get_report(report_id)
    if not report:
        return False
        
    # Delete database records (cascade deletion should ideally handle sessions/messages, 
    # but we'll delete them manually for robustness in SQLite if foreign key support is not enabled)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Enable foreign key constraint support for Cascade deletes
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        success = True
    except Exception as e:
        logger.error(f"Error deleting report from DB: {e}")
        success = False
    finally:
        conn.close()
        
    # Clean up files on disk
    if os.path.exists(report['file_path']):
        try:
            os.remove(report['file_path'])
        except Exception as e:
            logger.error(f"Error removing report file {report['file_path']}: {e}")
            
    # Clean up index files
    index_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.index")
    meta_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.meta")
    for p in [index_path, meta_path]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception as e:
                logger.error(f"Error removing vector file {p}: {e}")
                
    return success

def create_chat_session(session_id, report_id, title):
    """Creates a new chat session for a specific report."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO chat_sessions (session_id, report_id, title)
            VALUES (?, ?, ?)
        """, (session_id, report_id, title))
        conn.commit()
    except sqlite3.IntegrityError:
        # Ignore if it already exists
        pass
    conn.close()

def get_chat_sessions(report_id):
    """Gets all chat sessions associated with a report."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_sessions WHERE report_id = ? ORDER BY created_at DESC", (report_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_chat_messages(session_id):
    """Gets all chat messages for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        d = dict(row)
        if d['references_json']:
            try:
                d['references'] = json.loads(d['references_json'])
            except json.JSONDecodeError:
                d['references'] = []
        else:
            d['references'] = []
        messages.append(d)
    return messages

def add_chat_message(session_id, role, content, references_json=None, confidence_score=None):
    """Adds a new message to a chat session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_messages (session_id, role, content, references_json, confidence_score)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, role, content, references_json, confidence_score))
    conn.commit()
    conn.close()

def preload_default_report():
    """
    Checks if a default report is in the database. If not, parses the default XML file,
    saves it to the database, builds the local FAISS index, and generates its profile.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reports LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    if row:
        logger.info("Report database already initialized. Preloading skipped.")
        return
        
    logger.info("Preloading default report into database...")
    default_xml = "BRSR_532540_155202623553_BRSR_WebXMLFile_20260602_163936876.xml"
    if not os.path.exists(default_xml):
        logger.error(f"Preload failed: {default_xml} is missing in workspace root.")
        return
        
    try:
        # Move file to uploads folder if not already there
        dest_folder = Config.UPLOAD_FOLDER
        os.makedirs(dest_folder, exist_ok=True)
        dest_path = os.path.join(dest_folder, default_xml)
        if not os.path.exists(dest_path):
            import shutil
            shutil.copy(default_xml, dest_path)
            
        from parser import parse_xbrl_document
        metadata, facts, chunks = parse_xbrl_document(dest_path)
        
        # Save to database (without profile first)
        report_id = add_report(
            filename=default_xml,
            original_name="TCS BRSR Report 2026",
            file_path=dest_path,
            company_name=metadata.get('company_name', 'Tata Consultancy Services Limited'),
            reporting_period=metadata.get('reporting_period', '2026'),
            document_type=metadata.get('document_type', 'Sustainability Report'),
            esg_summary="Generating ESG summary...",
            company_profile="Generating profile..."
        )
        
        # Generate local embeddings
        from embeddings import EmbeddingGenerator
        from vector_store import VectorStore
        
        logger.info(f"Generating local embeddings for preloaded report {report_id}...")
        emb_gen = EmbeddingGenerator()
        embeddings = emb_gen.generate_embeddings([c['text'] for c in chunks])
        
        vs = VectorStore(report_id)
        vs.save(embeddings, chunks)
        logger.info(f"Local FAISS index saved for preloaded report {report_id}.")
        
        # Generate ESG summary and profile via Groq (non-blocking or simple call)
        from rag import RAGPipeline
        rag = RAGPipeline(report_id)
        esg_summary, company_profile = rag.generate_esg_summary_and_profile(facts, chunks)
        update_report_esg(report_id, esg_summary, company_profile)
        logger.info(f"Preloaded report {report_id} successfully parsed, indexed, and summarized.")
        
    except Exception as e:
        logger.error(f"Error during preloading default report: {e}")
        import traceback
        traceback.print_exc()

