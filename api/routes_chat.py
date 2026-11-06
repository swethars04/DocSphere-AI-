import uuid
import logging
from flask import Blueprint, request, jsonify, make_response, session as flask_session
from db.repositories import ChatRepository, CompanyRepository
from agents.pipeline import AgenticRAGPipeline
from api.routes_documents import hybrid_retriever
from core.security import login_required

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')

# Lazy-loaded pipeline instance
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = AgenticRAGPipeline(hybrid_retriever=hybrid_retriever)
    return _pipeline

def generate_relevant_chat_title(question: str, sub_queries: list = None) -> str:
    """Generates a concise, professional 3-6 word title relevant to the user query."""
    import re
    clean_q = question.strip()
    
    # 1. If sub_queries exist from PlannerAgent, they represent the distilled topic
    if sub_queries and len(sub_queries) > 0 and len(sub_queries[0]) > 4:
        first_sq = sub_queries[0].strip()
        words = first_sq.split()
        if len(words) >= 2:
            candidate = " ".join(words[:5]).title()
            if len(candidate) > 35:
                candidate = candidate[:35].rsplit(' ', 1)[0]
            if len(candidate) > 4:
                return candidate

    # 2. Extract from user query
    cleaned = re.sub(r'^(hi|hello|hey|please|can you|could you|tell me about|what is|what are|explain|give me|give the|give|find|search for)\b', '', clean_q, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^(the|a|an)\b', '', cleaned, flags=re.IGNORECASE).strip()
    words = cleaned.split()
    if not words:
        return "General Discussion"
    
    title = " ".join(words[:5]).strip()
    title = re.sub(r'[^\w\s\-\.]', '', title).strip().title()
    if len(title) > 35:
        title = title[:35].rsplit(' ', 1)[0]
    return title or "Document Query"

@chat_bp.route('/sessions', methods=['GET'])
@login_required
def list_sessions():
    """Lists all chat sessions sorted by recent activity for the current user."""
    user_id = flask_session.get('user_id')
    sessions = ChatRepository.get_all_sessions(user_id=user_id)
    return jsonify({"success": True, "sessions": sessions})

@chat_bp.route('/sessions', methods=['POST'])
@login_required
def create_session():
    """Creates a new chat session with optional pre-selected company filters."""
    user_id = flask_session.get('user_id')
    data = request.get_json() or {}
    session_id = str(uuid.uuid4())
    existing_sessions = ChatRepository.get_all_sessions(user_id=user_id)
    default_title = f"Chat #{len(existing_sessions) + 1}"
    title = data.get('title', default_title).strip() or default_title
    selected_company_ids = data.get('selected_company_ids', [])

    session = ChatRepository.create_session(
        session_id=session_id,
        title=title,
        selected_company_ids=selected_company_ids,
        user_id=user_id
    )
    return jsonify({"success": True, "session": session})

@chat_bp.route('/sessions/<string:session_id>', methods=['GET'])
@login_required
def get_session(session_id: str):
    """Retrieves session metadata and full message history with citations."""
    session = ChatRepository.get_session(session_id)
    if not session:
        return jsonify({"success": False, "message": "Session not found."}), 404

    messages = ChatRepository.get_session_messages(session_id)
    return jsonify({
        "success": True,
        "session": session,
        "messages": messages
    })

@chat_bp.route('/sessions/<string:session_id>', methods=['DELETE', 'POST'])
@chat_bp.route('/sessions/<string:session_id>/delete', methods=['DELETE', 'POST'])
@login_required
def delete_session(session_id: str):
    """Deletes a chat session and cascades all messages."""
    success = ChatRepository.delete_session(session_id)
    return jsonify({"success": success})

@chat_bp.route('/sessions/<string:session_id>/rename', methods=['POST'])
@login_required
def rename_session(session_id: str):
    """Renames an existing chat session."""
    data = request.get_json() or {}
    new_title = data.get('title', '').strip()
    if not new_title:
        return jsonify({"success": False, "message": "Title cannot be empty."}), 400
    success = ChatRepository.update_session_title(session_id, new_title)
    return jsonify({"success": success, "new_title": new_title})


@chat_bp.route('/sessions/<string:session_id>/filter', methods=['POST'])
@login_required
def update_filter(session_id: str):
    """Updates the company filter applied to the session."""
    data = request.get_json() or {}
    company_ids = data.get('selected_company_ids', [])
    ChatRepository.update_session_filter(session_id, company_ids)
    return jsonify({"success": True, "selected_company_ids": company_ids})

@chat_bp.route('/sessions/<string:session_id>/message', methods=['POST'])
@login_required
def send_message(session_id: str):
    """
    Executes the 4-agent self-correcting RAG pipeline.
    Applies company filtering, audits factuality, and stores verifiable citations.
    """
    session = ChatRepository.get_session(session_id)
    if not session:
        return jsonify({"success": False, "message": "Session not found."}), 404

    data = request.get_json() or {}
    user_prompt = data.get('message', '').strip()
    if not user_prompt:
        return jsonify({"success": False, "message": "Message content cannot be empty."}), 400

    # Determine company filter (request override or session setting)
    company_ids = data.get('company_ids')
    if company_ids is None:
        company_ids = session.get('selected_company_ids', [])

    company_names = []
    if company_ids:
        companies = CompanyRepository.get_multiple_by_ids(company_ids)
        company_names = [c['name'] for c in companies]

    # Determine if auto-titling is needed for this session
    current_title = session.get('title', '')
    is_default_title = (
        not current_title or 
        current_title.startswith("Chat #") or 
        current_title in ["New Discussion", "New Chat Session", "New Query", "Welcome Discussion", "Live Qwen Chat Session"]
    )

    new_title = None
    if is_default_title:
        try:
            new_title = generate_relevant_chat_title(user_prompt)
            if new_title:
                ChatRepository.update_session_title(session_id, new_title)
        except Exception as e:
            logger.warning(f"Could not early auto-title session {session_id}: {e}")

    try:
        # 1. Store user message in database
        ChatRepository.add_message(
            session_id=session_id,
            role="user",
            content=user_prompt
        )

        # 2. Retrieve recent chat history
        history = ChatRepository.get_session_messages(session_id)

        # 3. Execute Multi-Agent RAG Pipeline scoped to user's documents
        pipeline = get_pipeline()
        rag_output = pipeline.answer_query(
            question=user_prompt,
            chat_history=history[:-1],  # exclude current message just added
            company_names=company_names,
            user_id=flask_session.get('user_id')
        )

        # 4. Save assistant response with audit logs
        assistant_msg_id = ChatRepository.add_message(
            session_id=session_id,
            role="assistant",
            content=rag_output["answer"],
            confidence=rag_output.get("confidence", "Medium"),
            reasoning=rag_output.get("reasoning", ""),
            verification_attempts=rag_output.get("attempts", 1)
        )

        # 5. Persist granular citations
        saved_citations = []
        for cite in rag_output.get("citations", []):
            cid = ChatRepository.add_citation(
                message_id=assistant_msg_id,
                document_id=None,
                company_name=cite.get("company_name", "Unknown"),
                document_name=cite.get("document_name", "Unknown Document"),
                page_or_section=cite.get("page_or_section", "General"),
                excerpt=cite.get("excerpt", ""),
                relevance_score=cite.get("relevance_score", 0.9)
            )
            cite["id"] = cid
            saved_citations.append(cite)

        # 6. Refine title with sub-queries if planner produced high-quality topic distillation
        if is_default_title and rag_output.get("sub_queries"):
            try:
                refined_title = generate_relevant_chat_title(user_prompt, rag_output.get("sub_queries"))
                if refined_title and refined_title != new_title:
                    new_title = refined_title
                    ChatRepository.update_session_title(session_id, new_title)
            except Exception as e:
                pass

        return jsonify({
            "success": True,
            "message_id": assistant_msg_id,
            "answer": rag_output["answer"],
            "confidence": rag_output["confidence"],
            "reasoning": rag_output["reasoning"],
            "attempts": rag_output["attempts"],
            "citations": saved_citations,
            "new_title": new_title
        })


    except Exception as e:
        logger.error(f"Error executing agent pipeline: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@chat_bp.route('/sessions/<string:session_id>/export', methods=['GET'])
@login_required
def export_session(session_id: str):
    """Generates downloadable Markdown transcript with verifiable citations."""
    session = ChatRepository.get_session(session_id)
    if not session:
        return "Session not found", 404

    messages = ChatRepository.get_session_messages(session_id)
    content = f"# DocSphere AI: Chat Session Transcript\n"
    content += f"**Session Title:** {session['title']}\n"
    content += f"**Export Date:** {session['updated_at']}\n\n---\n\n"

    for msg in messages:
        role = "USER" if msg['role'] == 'user' else "ASSISTANT (DocSphere AI)"
        content += f"### {role} ({msg['timestamp']})\n"
        if msg.get('confidence'):
            content += f"*Confidence Score: {msg['confidence']}*\n\n"
        content += f"{msg['content']}\n\n"

        citations = msg.get('citations', [])
        if citations:
            content += "**Verified Source Citations:**\n"
            for c in citations:
                content += f"- **[{c['company_name']}]** {c['document_name']} — *{c['page_or_section']}*\n"
                content += f"  > \"{c['excerpt']}\"\n"
            content += "\n"
        content += "---\n\n"

    response = make_response(content)
    response.headers["Content-Disposition"] = f"attachment; filename=chat_{session_id[:8]}.md"
    response.headers["Content-Type"] = "text/markdown; charset=utf-8"
    return response
