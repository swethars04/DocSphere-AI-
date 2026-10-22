import json
import logging
from typing import List, Dict, Any, Optional
from db.database import get_db_connection

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. COMPANY REPOSITORY
# ==============================================================================
class CompanyRepository:
    """Manages organization/company records for metadata tagging and filtering."""

    @staticmethod
    def get_or_create(name: str, sector: Optional[str] = None, ticker: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        """Fetches existing company by name (case-insensitive) or inserts a new one."""
        clean_name = name.strip()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE name = ? COLLATE NOCASE", (clean_name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
                
            cursor.execute(
                """
                INSERT INTO companies (name, ticker_or_code, sector, description)
                VALUES (?, ?, ?, ?)
                """,
                (clean_name, ticker, sector, description)
            )
            company_id = cursor.lastrowid
            cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
            return dict(cursor.fetchone())

    @staticmethod
    def get_all() -> List[Dict[str, Any]]:
        """Retrieves all registered companies along with their document counts."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.*, COUNT(d.id) AS document_count
                FROM companies c
                LEFT JOIN documents d ON c.id = d.company_id
                GROUP BY c.id
                ORDER BY c.name ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(company_id: int) -> Optional[Dict[str, Any]]:
        """Finds a company by primary key."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict[str, Any]]:
        """Finds a company by exact or case-insensitive name."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE name = ? COLLATE NOCASE", (name.strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_multiple_by_ids(company_ids: List[int]) -> List[Dict[str, Any]]:
        """Retrieves multiple companies given a list of IDs."""
        if not company_ids:
            return []
        placeholders = ",".join("?" for _ in company_ids)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM companies WHERE id IN ({placeholders})", company_ids)
            return [dict(row) for row in cursor.fetchall()]


# ==============================================================================
# 2. DOCUMENT REPOSITORY
# ==============================================================================
class DocumentRepository:
    """Manages multi-format document assets and their indexing status."""

    @staticmethod
    def add_document(
        company_id: int,
        filename: str,
        original_name: str,
        file_type: str,
        file_path: str,
        file_size_bytes: int = 0,
        total_pages_or_sections: int = 1,
        chunk_count: int = 0,
        status: str = "indexed"
    ) -> int:
        """Registers a parsed and indexed document under a company."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO documents (
                    company_id, filename, original_name, file_type,
                    file_path, file_size_bytes, total_pages_or_sections,
                    chunk_count, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id, filename, original_name, file_type.lower(),
                    file_path, file_size_bytes, total_pages_or_sections,
                    chunk_count, status
                )
            )
            return cursor.lastrowid

    @staticmethod
    def get_all(company_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieves documents, optionally filtered by company ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if company_id:
                cursor.execute("""
                    SELECT d.*, c.name AS company_name
                    FROM documents d
                    JOIN companies c ON d.company_id = c.id
                    WHERE d.company_id = ?
                    ORDER BY d.created_at DESC
                """, (company_id,))
            else:
                cursor.execute("""
                    SELECT d.*, c.name AS company_name
                    FROM documents d
                    JOIN companies c ON d.company_id = c.id
                    ORDER BY d.created_at DESC
                """)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(doc_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a document with company details."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT d.*, c.name AS company_name
                FROM documents d
                JOIN companies c ON d.company_id = c.id
                WHERE d.id = ?
            """, (doc_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_company_ids(company_ids: List[int]) -> List[Dict[str, Any]]:
        """Retrieves documents belonging to a list of company IDs."""
        if not company_ids:
            return []
        placeholders = ",".join("?" for _ in company_ids)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT d.*, c.name AS company_name
                FROM documents d
                JOIN companies c ON d.company_id = c.id
                WHERE d.company_id IN ({placeholders})
                ORDER BY d.created_at DESC
            """, company_ids)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update_status(doc_id: int, status: str, chunk_count: Optional[int] = None):
        """Updates document indexing status and chunk count."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if chunk_count is not None:
                cursor.execute(
                    "UPDATE documents SET status = ?, chunk_count = ? WHERE id = ?",
                    (status, chunk_count, doc_id)
                )
            else:
                cursor.execute("UPDATE documents SET status = ? WHERE id = ?", (status, doc_id))

    @staticmethod
    def rename(doc_id: int, new_name: str) -> bool:
        """Renames a document's display name."""
        clean_name = new_name.strip()
        if not clean_name:
            return False
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE documents SET original_name = ? WHERE id = ?",
                (clean_name, doc_id)
            )
            return cursor.rowcount > 0

    @staticmethod
    def delete(doc_id: int) -> bool:
        """Deletes a document record and cascades citations."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            return cursor.rowcount > 0


# ==============================================================================
# 3. CHAT REPOSITORY
# ==============================================================================
class ChatRepository:
    """Manages multi-turn conversation sessions, messages, and citations."""

    @staticmethod
    def create_session(session_id: str, title: str, selected_company_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """Creates a new isolated chat session with optional company filters."""
        companies_json = json.dumps(selected_company_ids or [])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(chat_sessions);")
            cols = {row['name'] for row in cursor.fetchall()}
            if 'report_id' in cols:
                cursor.execute(
                    """
                    INSERT INTO chat_sessions (session_id, report_id, title, selected_company_ids)
                    VALUES (?, 1, ?, ?)
                    """,
                    (session_id, title, companies_json)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO chat_sessions (session_id, title, selected_company_ids)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, title, companies_json)
                )
            return {
                "session_id": session_id,
                "title": title,
                "selected_company_ids": selected_company_ids or []
            }

    @staticmethod
    def get_session(session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves session metadata by UUID."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["selected_company_ids"] = json.loads(res.get("selected_company_ids", "[]"))
            except Exception:
                res["selected_company_ids"] = []
            return res

    @staticmethod
    def get_all_sessions() -> List[Dict[str, Any]]:
        """Retrieves all chat sessions sorted by most recent activity."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC")
            sessions = []
            for row in cursor.fetchall():
                item = dict(row)
                try:
                    item["selected_company_ids"] = json.loads(item.get("selected_company_ids", "[]"))
                except Exception:
                    item["selected_company_ids"] = []
                sessions.append(item)
            return sessions

    @staticmethod
    def update_session_filter(session_id: str, selected_company_ids: List[int]):
        """Updates the company filter applied to an existing session."""
        companies_json = json.dumps(selected_company_ids or [])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE chat_sessions
                SET selected_company_ids = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (companies_json, session_id)
            )

    @staticmethod
    def update_session_title(session_id: str, title: str) -> bool:
        """Updates the topic title of a chat session."""
        clean_title = title.strip()
        if not clean_title:
            return False
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (clean_title, session_id)
            )
            return cursor.rowcount > 0

    @staticmethod
    def update_session_timestamp(session_id: str):

        """Refreshes session last active timestamp."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )

    @staticmethod
    def delete_session(session_id: str) -> bool:
        """Deletes a chat session along with all related messages and citations."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            return cursor.rowcount > 0

    @staticmethod
    def add_message(
        session_id: str,
        role: str,
        content: str,
        confidence: Optional[str] = None,
        reasoning: Optional[str] = None,
        verification_attempts: int = 1
    ) -> int:
        """Appends a user or assistant message to the session stream."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO chat_messages (
                    session_id, role, content, confidence, reasoning, verification_attempts
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, confidence, reasoning, verification_attempts)
            )
            msg_id = cursor.lastrowid
            
            # Bump session updated_at
            cursor.execute(
                "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )
            return msg_id

    @staticmethod
    def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
        """Retrieves chronological messages for a session including citations."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            )
            messages = [dict(row) for row in cursor.fetchall()]
            
            for msg in messages:
                if msg["role"] == "assistant":
                    cursor.execute(
                        "SELECT * FROM citations WHERE message_id = ? ORDER BY relevance_score DESC",
                        (msg["id"],)
                    )
                    msg["citations"] = [dict(c) for c in cursor.fetchall()]
                else:
                    msg["citations"] = []
            return messages

    @staticmethod
    def add_citation(
        message_id: int,
        document_id: Optional[int],
        company_name: str,
        document_name: str,
        page_or_section: str,
        excerpt: str,
        relevance_score: float = 0.0
    ) -> int:
        """Stores a verifiable citation link for an assistant message."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO citations (
                    message_id, document_id, company_name,
                    document_name, page_or_section, excerpt, relevance_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id, document_id, company_name,
                    document_name, page_or_section, excerpt, relevance_score
                )
            )
            return cursor.lastrowid

    @staticmethod
    def get_message_citations(message_id: int) -> List[Dict[str, Any]]:
        """Fetches citations supporting a specific message."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM citations WHERE message_id = ? ORDER BY relevance_score DESC",
                (message_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
