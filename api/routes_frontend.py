import uuid
import logging
from flask import Blueprint, render_template, redirect, url_for, request, session
from db.repositories import CompanyRepository, DocumentRepository, ChatRepository
from core.security import login_required, admin_required

logger = logging.getLogger(__name__)
frontend_bp = Blueprint('frontend', __name__)

@frontend_bp.route('/')
@login_required
def index():
    """Renders the central document management & company catalog dashboard scoped to user."""
    user_id = session.get('user_id')
    companies = CompanyRepository.get_all(user_id=user_id)
    documents = DocumentRepository.get_all(user_id=user_id)
    recent_sessions = ChatRepository.get_all_sessions(user_id=user_id)
    return render_template(
        'index.html',
        companies=companies,
        documents=documents,
        recent_sessions=recent_sessions[:5]
    )

@frontend_bp.route('/documents')
@login_required
def documents():
    """Renders the comprehensive Document Storage & Management repository scoped to user."""
    user_id = session.get('user_id')
    companies = CompanyRepository.get_all(user_id=user_id)
    all_docs = DocumentRepository.get_all(user_id=user_id)
    return render_template(
        'documents.html',
        companies=companies,
        documents=all_docs
    )

@frontend_bp.route('/database')
@admin_required
def database_viewer():
    """Renders the built-in database explorer with live table views (Admin Only)."""
    import sqlite3
    from config import Config
    db_path = Config.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = ['users', 'documents', 'companies', 'chat_sessions', 'chat_messages', 'citations']
    tables_data = {}
    for t in tables:
        try:
            if t == 'documents':
                cursor.execute("""
                    SELECT 
                        d.id,
                        d.original_name,
                        COALESCE(u.full_name, 'System') AS uploader_name,
                        COALESCE(u.email, 'system@docusphere.ai') AS uploader_email,
                        COALESCE(u.role, 'admin') AS uploader_role,
                        d.user_id,
                        COALESCE(c.name, 'General') AS organization,
                        d.file_type,
                        d.file_size_bytes,
                        d.total_pages_or_sections,
                        d.chunk_count,
                        d.status,
                        d.created_at
                    FROM documents d
                    LEFT JOIN users u ON d.user_id = u.id
                    LEFT JOIN companies c ON d.company_id = c.id
                    ORDER BY d.id DESC
                """)
            elif t == 'chat_sessions':
                cursor.execute("""
                    SELECT 
                        s.session_id,
                        s.title,
                        COALESCE(u.full_name, 'Unknown') AS user_name,
                        COALESCE(u.email, 'unknown@user.com') AS user_email,
                        COALESCE(u.role, 'analyst') AS user_role,
                        s.user_id,
                        s.created_at,
                        s.updated_at
                    FROM chat_sessions s
                    LEFT JOIN users u ON s.user_id = u.id
                    ORDER BY s.updated_at DESC
                """)
            else:
                cursor.execute(f"PRAGMA table_info({t});")
                col_names = [col['name'] for col in cursor.fetchall()]
                if 'id' in col_names:
                    cursor.execute(f"SELECT * FROM {t} ORDER BY id DESC")
                elif 'updated_at' in col_names:
                    cursor.execute(f"SELECT * FROM {t} ORDER BY updated_at DESC")
                elif 'created_at' in col_names:
                    cursor.execute(f"SELECT * FROM {t} ORDER BY created_at DESC")
                else:
                    cursor.execute(f"SELECT * FROM {t}")
            tables_data[t] = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading table {t} for database viewer: {e}")
            tables_data[t] = []
    conn.close()

    return render_template('database.html', tables_data=tables_data)

@frontend_bp.route('/chat/new')
@login_required
def new_chat():
    """Explicitly creates a new chat session and redirects to it."""
    user_id = session.get('user_id')
    new_id = str(uuid.uuid4())
    sessions = ChatRepository.get_all_sessions(user_id=user_id)
    session_num = len(sessions) + 1
    ChatRepository.create_session(new_id, f"Chat #{session_num}", user_id=user_id)
    return redirect(url_for('frontend.chat', session_id=new_id))


@frontend_bp.route('/chat')
@frontend_bp.route('/chat/<string:session_id>')
@login_required
def chat(session_id=None):
    """Renders the 3-column multi-agent grounded chat workspace."""
    user_id = session.get('user_id')
    companies = CompanyRepository.get_all(user_id=user_id)
    sessions = ChatRepository.get_all_sessions(user_id=user_id)

    # If no session specified, pick latest or create a default session
    if not session_id:
        if sessions:
            return redirect(url_for('frontend.chat', session_id=sessions[0]['session_id']))
        else:
            new_id = str(uuid.uuid4())
            ChatRepository.create_session(new_id, "Chat #1", user_id=user_id)
            return redirect(url_for('frontend.chat', session_id=new_id))

    current_session = ChatRepository.get_session(session_id)
    if not current_session:
        return redirect(url_for('frontend.chat'))

    messages = ChatRepository.get_session_messages(session_id)
    return render_template(
        'chat.html',
        current_session=current_session,
        sessions=sessions,
        companies=companies,
        messages=messages
    )
