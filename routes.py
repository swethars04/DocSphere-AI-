import os
import uuid
import logging
import requests
import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file
from werkzeug.utils import secure_filename
from config import Config
import utils.db_helper as db
from parser import validate_xbrl_file, parse_xbrl_document
from embeddings import ApiKeyMissingException
from vector_store import VectorStore
from rag import RAGPipeline

logger = logging.getLogger(__name__)
bp = Blueprint('routes', __name__)

def allowed_file(filename):
    """Checks if the uploaded file has a valid XML, HTML, or XBRL extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'xml', 'xbrl', 'html', 'xhtml', 'htm'}

@bp.route('/')
def index():
    """Renders the dashboard landing page listing all reports."""
    reports = db.get_reports()
    selected_report_id = request.args.get('report_id', type=int)
    
    if not selected_report_id and reports:
        # Redirect to the preloaded default report
        return redirect(url_for('routes.index', report_id=reports[0]['id']))
        
    selected_report = None
    if selected_report_id:
        selected_report = db.get_report(selected_report_id)
        
    return render_template('index.html', reports=reports, selected_report=selected_report)

@bp.route('/search_company', methods=['POST'])
def search_company():
    """
    Handles searching for a company report. If the report is registered, redirects to dashboard.
    If not, automatically triggers the scraper to retrieve, parse, and index the report.
    """
    data = request.get_json() or {}
    company_name = data.get('company_name', '').strip()
    
    if not company_name:
        return jsonify({'success': False, 'message': 'Company name is required.'}), 400
        
    try:
        # 1. Check if the company is already registered in our DB
        existing_report = db.find_report_by_company(company_name)
        if existing_report:
            logger.info(f"Company '{company_name}' already exists in database with report ID: {existing_report['id']}")
            return jsonify({
                'success': True,
                'message': 'Company report found in database.',
                'report_id': existing_report['id']
            })
            
        # 2. Trigger automatic scraper
        from utils.scraper import download_report_for_company
        logger.info(f"Company '{company_name}' not found. Triggering automatic scraping...")
        
        file_path = download_report_for_company(company_name, year=2026)
        if not file_path or not os.path.exists(file_path):
            return jsonify({
                'success': False,
                'message': f"Could not find or retrieve a sustainability report for '{company_name}'."
            }), 404
            
        # 3. Parse downloaded report
        metadata, facts, chunks = parse_xbrl_document(file_path)
        
        # 4. Insert into database
        report_id = db.add_report(
            filename=os.path.basename(file_path),
            original_name=f"{company_name} Sustainability Report 2026",
            file_path=file_path,
            company_name=metadata['company_name'],
            reporting_period=metadata['reporting_period'],
            document_type=metadata['document_type'],
            esg_summary="Generating ESG summary...",
            company_profile="Extracting profile..."
        )
        
        # 5. Build FAISS index and generate ESG summary via Groq
        chunk_texts = [c['text'] for c in chunks]
        from embeddings import EmbeddingGenerator
        embedder = EmbeddingGenerator()
        embeddings = embedder.generate_embeddings(chunk_texts)
        
        vs = VectorStore(report_id)
        vs.save(embeddings, chunks)
        
        rag = RAGPipeline(report_id)
        esg_summary, company_profile, predefined_prompts = rag.generate_esg_summary_and_profile(facts, chunks)
        db.update_report_esg(report_id, esg_summary, company_profile, json.dumps(predefined_prompts))
        
        logger.info(f"Successfully scraped, parsed, and indexed report for '{company_name}' (ID: {report_id})")
        return jsonify({
            'success': True,
            'message': 'Sustainability report scraped and parsed successfully.',
            'report_id': report_id
        })
        
    except Exception as e:
        logger.error(f"Error searching/scraping company '{company_name}': {e}")
        return jsonify({'success': False, 'message': str(e)}), 400

@bp.route('/upload', methods=['POST'])
def upload_file():
    """Handles uploading an XBRL file from the local machine."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part in the request.'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected.'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file extension. Please upload an XML, XBRL, or HTML file.'}), 400
        
    filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
    file_path = os.path.join(Config.UPLOAD_FOLDER, filename)
    
    try:
        # Save file to disk
        file.save(file_path)
        
        # Validate file contents
        is_valid, validation_msg = validate_xbrl_file(file_path)
        if not is_valid:
            os.remove(file_path)
            return jsonify({'success': False, 'message': validation_msg}), 400
            
        # Parse document
        metadata, facts, chunks = parse_xbrl_document(file_path)
        
        # Insert report into Database with placeholders
        report_id = db.add_report(
            filename=filename,
            original_name=file.filename,
            file_path=file_path,
            company_name=metadata['company_name'],
            reporting_period=metadata['reporting_period'],
            document_type=metadata['document_type'],
            esg_summary="Generating ESG summary...",
            company_profile="Extracting company profile..."
        )
        
        # Build Vector Store & generate ESG summary if API key is present
        api_key_status = True
        esg_summary = ""
        company_profile = ""
        
        try:
            # Generate chunks list
            chunk_texts = [c['text'] for c in chunks]
            
            # Generate Embeddings
            from embeddings import EmbeddingGenerator
            embedder = EmbeddingGenerator()
            embeddings = embedder.generate_embeddings(chunk_texts)
            
            # Save to FAISS index
            vs = VectorStore(report_id)
            vs.save(embeddings, chunks)
            
            # Generate ESG Summary and Company Profile
            rag = RAGPipeline(report_id)
            esg_summary, company_profile, predefined_prompts = rag.generate_esg_summary_and_profile(facts, chunks)
            db.update_report_esg(report_id, esg_summary, company_profile, json.dumps(predefined_prompts))
            
        except ApiKeyMissingException:
            api_key_status = False
            esg_summary = (
                "### API Key Required\n\n"
                "The report was uploaded and parsed successfully, but the ESG summary generation and "
                "vector index building were skipped because **GROQ_API_KEY is not configured** in your `.env` file.\n\n"
                "Please add your Groq API key and restart the server to enable AI capabilities."
            )
            company_profile = "API Key not configured. Profile extraction skipped."
            db.update_report_esg(report_id, esg_summary, company_profile, None)
            
        return jsonify({
            'success': True,
            'message': 'Report uploaded and parsed successfully.',
            'report_id': report_id,
            'api_key_configured': api_key_status
        })
        
    except Exception as e:
        logger.error(f"Error handling upload: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'success': False, 'message': f"Internal error during upload: {str(e)}"}), 500

@bp.route('/upload-url', methods=['POST'])
def upload_url():
    """Downloads an XBRL file from a URL and parses it."""
    url = request.json.get('url')
    if not url:
        return jsonify({'success': False, 'message': 'No URL provided.'}), 400
        
    original_name = url.split('/')[-1]
    if not original_name or '.' not in original_name:
        original_name = "sustainability_report.xml"
        
    if not allowed_file(original_name):
        original_name += ".xml"  # force extension
        
    filename = secure_filename(f"{uuid.uuid4()}_{original_name}")
    file_path = os.path.join(Config.UPLOAD_FOLDER, filename)
    
    try:
        # Download from URL
        response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code != 200:
            return jsonify({'success': False, 'message': f"Failed to download report. HTTP Status Code: {response.status_code}"}), 400
            
        with open(file_path, 'wb') as f:
            f.write(response.content)
            
        # Validate file contents
        is_valid, validation_msg = validate_xbrl_file(file_path)
        if not is_valid:
            os.remove(file_path)
            return jsonify({'success': False, 'message': validation_msg}), 400
            
        # Parse document
        metadata, facts, chunks = parse_xbrl_document(file_path)
        
        # Insert report into Database
        report_id = db.add_report(
            filename=filename,
            original_name=original_name,
            file_path=file_path,
            company_name=metadata['company_name'],
            reporting_period=metadata['reporting_period'],
            document_type=metadata['document_type'],
            esg_summary="Generating ESG summary...",
            company_profile="Extracting company profile..."
        )
        
        # Build Vector Store & generate ESG summary if API key is present
        api_key_status = True
        esg_summary = ""
        company_profile = ""
        
        try:
            # Generate chunks list
            chunk_texts = [c['text'] for c in chunks]
            
            from embeddings import EmbeddingGenerator
            embedder = EmbeddingGenerator()
            embeddings = embedder.generate_embeddings(chunk_texts)
            
            vs = VectorStore(report_id)
            vs.save(embeddings, chunks)
            
            rag = RAGPipeline(report_id)
            esg_summary, company_profile, predefined_prompts = rag.generate_esg_summary_and_profile(facts, chunks)
            db.update_report_esg(report_id, esg_summary, company_profile, json.dumps(predefined_prompts))
            
        except ApiKeyMissingException:
            api_key_status = False
            esg_summary = (
                "### API Key Required\n\n"
                "The report was downloaded and parsed successfully, but the ESG summary generation and "
                "vector index building were skipped because **GROQ_API_KEY is not configured** in your `.env` file.\n\n"
                "Please add your Groq API key and restart the server to enable AI capabilities."
            )
            company_profile = "API Key not configured. Profile extraction skipped."
            db.update_report_esg(report_id, esg_summary, company_profile, None)
            
        return jsonify({
            'success': True,
            'message': 'Report downloaded and parsed successfully.',
            'report_id': report_id,
            'api_key_configured': api_key_status
        })
        
    except Exception as e:
        logger.error(f"Error handling URL download: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'success': False, 'message': f"Internal error during URL fetch: {str(e)}"}), 500

@bp.route('/chat/<int:report_id>')
def chat(report_id):
    """Renders the Chat interface for the selected report."""
    report = db.get_report(report_id)
    if not report:
        return redirect(url_for('routes.index'))
        
    # Check if vector index exists
    index_exists = VectorStore.get_index_status(report_id)
    
    return render_template('chat.html', report=report, index_exists=index_exists)

@bp.route('/chat/prompts/<int:report_id>', methods=['GET'])
def get_report_prompts(report_id):
    """Fetches dynamically generated predefined prompts for the report, or defaults."""
    report = db.get_report(report_id)
    if not report:
        return jsonify({'success': False, 'message': 'Report not found.'}), 404
        
    prompts_json = report.get('predefined_prompts')
    if prompts_json:
        try:
            import json
            prompts = json.loads(prompts_json)
            if isinstance(prompts, list) and len(prompts) >= 4:
                return jsonify({'success': True, 'prompts': prompts[:4]})
        except Exception as e:
            logger.error(f"Error parsing predefined prompts for report {report_id}: {e}")
            
    # Fallback to smart default prompts if not generated yet
    company_name = report.get('company_name', 'this company')
    return jsonify({
        'success': True,
        'prompts': [
            f"What are the carbon footprint mitigation targets for {company_name}?",
            f"Compare the Scope 1 and Scope 2 greenhouse emissions of {company_name}.",
            f"What employee diversity and inclusion metrics are disclosed for {company_name}?",
            f"Explain the governance risk management policies of {company_name}."
        ]
    })

@bp.route('/chat/sessions/<int:report_id>', methods=['GET'])
def get_sessions(report_id):
    """Gets all chat sessions for a specific report."""
    sessions = db.get_chat_sessions(report_id)
    return jsonify(sessions)

@bp.route('/chat/session/create/<int:report_id>', methods=['POST'])
def create_session(report_id):
    """Creates a new chat session."""
    session_id = str(uuid.uuid4())
    title = request.json.get('title', 'New Chat Session')
    db.create_chat_session(session_id, report_id, title)
    return jsonify({'session_id': session_id, 'title': title})

@bp.route('/chat/session/<string:session_id>/messages', methods=['GET'])
def get_messages(session_id):
    """Gets all chat messages for a specific session."""
    messages = db.get_chat_messages(session_id)
    return jsonify(messages)

@bp.route('/chat/<int:report_id>/message', methods=['POST'])
def send_message(report_id):
    """Receives a message, retrieves context, queries LLM, saves it, and returns the response."""
    data = request.json
    question = data.get('message')
    session_id = data.get('session_id')
    
    if not question or not session_id:
        return jsonify({'success': False, 'message': 'Missing message or session ID.'}), 400
        
    report = db.get_report(report_id)
    if not report:
        return jsonify({'success': False, 'message': 'Report not found.'}), 404
        
    try:
        # Save user message
        db.add_chat_message(session_id, 'user', question)
        
        # Load chat history for context
        history = db.get_chat_messages(session_id)
        
        # Instantiate RAG pipeline
        rag = RAGPipeline(report_id)
        
        # Query LLM
        response_data = rag.query(question, history[:-1]) # exclude the user's message we just added since it's passed as current query
        
        # Save assistant response
        import json
        references_json = json.dumps(response_data['references'], ensure_ascii=False)
        db.add_chat_message(
            session_id=session_id,
            role='assistant',
            content=response_data['answer'],
            references_json=references_json,
            confidence_score=1.0 if response_data['confidence'] == 'High' else (0.5 if response_data['confidence'] == 'Medium' else 0.1)
        )
        
        return jsonify({
            'success': True,
            'answer': response_data['answer'],
            'confidence': response_data['confidence'],
            'reasoning': response_data['reasoning'],
            'references': response_data['references']
        })
        
    except Exception as e:
        logger.error(f"Error querying RAG: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/reset/<int:report_id>', methods=['POST'])
def reset_report(report_id):
    """Deletes a report, its DB records, files, and vector index."""
    success = db.delete_report(report_id)
    if success:
        return jsonify({'success': True, 'message': 'Report knowledge base reset successfully.'})
    else:
        return jsonify({'success': False, 'message': 'Failed to delete report.'}), 400

@bp.route('/chat/session/<string:session_id>/download')
def download_chat(session_id):
    """Downloads chat history as a formatted Markdown text file."""
    messages = db.get_chat_messages(session_id)
    if not messages:
        return "No chat history found for this session.", 404
        
    content = "# AI Sustainability Assistant - Chat Session History\n\n"
    for msg in messages:
        role = "USER" if msg['role'] == 'user' else "ASSISTANT"
        content += f"### {role} ({msg['timestamp']})\n"
        content += f"{msg['content']}\n\n"
        
        if msg['references']:
            content += "**References Used:**\n"
            for ref in msg['references']:
                content += f"- *Source:* {ref['source']}\n"
                content += f"  *Content:* {ref['text']}\n"
            content += "\n"
            
        content += "---\n\n"
        
    # Create temporary scratch directory or return content directly as a file response
    # We can write a custom Response using flask.make_response
    from flask import make_response
    response = make_response(content)
    response.headers["Content-Disposition"] = f"attachment; filename=chat_history_{session_id[:8]}.md"
    response.headers["Content-type"] = "text/markdown; charset=utf-8"
    return response
