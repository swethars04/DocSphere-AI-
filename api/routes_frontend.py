import uuid
from flask import Blueprint, render_template, redirect, url_for, request
from db.repositories import CompanyRepository, DocumentRepository, ChatRepository

frontend_bp = Blueprint('frontend', __name__)

@frontend_bp.route('/')
def index():
    """Renders the central document management & company catalog dashboard."""
    companies = CompanyRepository.get_all()
    documents = DocumentRepository.get_all()
    recent_sessions = ChatRepository.get_all_sessions()
    return render_template(
        'index.html',
        companies=companies,
        documents=documents,
        recent_sessions=recent_sessions[:5]
    )

@frontend_bp.route('/documents')
def documents():
    """Renders the comprehensive Document Storage & Management repository."""
    companies = CompanyRepository.get_all()
    all_docs = DocumentRepository.get_all()
    return render_template(
        'documents.html',
        companies=companies,
        documents=all_docs
    )

@frontend_bp.route('/database')
def database_viewer():
    """Renders the built-in database explorer with live table views."""
    import sqlite3
    from config import Config
    db_path = Config.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = ['documents', 'companies', 'chat_sessions', 'chat_messages', 'citations']
    tables_data = {}
    for t in tables:
        try:
            cursor.execute(f"SELECT * FROM {t} ORDER BY id DESC")
            tables_data[t] = [dict(r) for r in cursor.fetchall()]
        except Exception:
            tables_data[t] = []
    conn.close()

    return render_template('database.html', tables_data=tables_data)

@frontend_bp.route('/chat/new')
def new_chat():
    """Explicitly creates a new chat session and redirects to it."""
    new_id = str(uuid.uuid4())
    sessions = ChatRepository.get_all_sessions()
    session_num = len(sessions) + 1
    ChatRepository.create_session(new_id, f"Chat #{session_num}")
    return redirect(url_for('frontend.chat', session_id=new_id))


@frontend_bp.route('/chat')
@frontend_bp.route('/chat/<string:session_id>')
def chat(session_id=None):
    """Renders the 3-column multi-agent grounded chat workspace."""
    companies = CompanyRepository.get_all()
    sessions = ChatRepository.get_all_sessions()

    # If no session specified, pick latest or create a default session
    if not session_id:
        if sessions:
            return redirect(url_for('frontend.chat', session_id=sessions[0]['session_id']))
        else:
            new_id = str(uuid.uuid4())
            ChatRepository.create_session(new_id, "Chat #1")
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
