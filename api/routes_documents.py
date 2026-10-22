import os
import uuid
import logging
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from config import Config
from db.repositories import CompanyRepository, DocumentRepository
from core.factory import DocumentParserFactory
from indexing.hybrid_retriever import HybridRetriever

logger = logging.getLogger(__name__)
documents_bp = Blueprint('documents', __name__, url_prefix='/api')

# Instantiate shared hybrid retriever
hybrid_retriever = HybridRetriever()

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

@documents_bp.route('/companies', methods=['GET'])
def get_companies():
    """Returns all registered companies with their document counts."""
    companies = CompanyRepository.get_all()
    return jsonify({"success": True, "companies": companies})

@documents_bp.route('/companies', methods=['POST'])
def create_company():
    """Manually registers an organization/company."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"success": False, "message": "Company name is required."}), 400
        
    company = CompanyRepository.get_or_create(
        name=name,
        sector=data.get('sector'),
        ticker=data.get('ticker'),
        description=data.get('description')
    )
    return jsonify({"success": True, "company": company})

@documents_bp.route('/documents', methods=['GET'])
def get_documents():
    """Lists documents, optionally filtered by company_id."""
    company_id = request.args.get('company_id', type=int)
    docs = DocumentRepository.get_all(company_id=company_id)
    return jsonify({"success": True, "documents": docs})

@documents_bp.route('/documents/upload', methods=['POST'])
def upload_documents():
    """
    Handles batch upload of multi-format documents (PDF, DOCX, TXT, HTML, XBRL).
    Extracts text, builds semantic chunks, binds company metadata, and indexes into Hybrid store.
    """
    company_name = request.form.get('company_name', '').strip()
    if not company_name:
        company_name = "General"

    if 'files' not in request.files:
        return jsonify({"success": False, "message": "No files provided in request."}), 400

    uploaded_files = request.files.getlist('files')
    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({"success": False, "message": "No files selected."}), 400

    # 1. Resolve or create company record
    company = CompanyRepository.get_or_create(name=company_name)
    company_id = company['id']

    processed_docs = []
    errors = []

    for file in uploaded_files:
        orig_filename = file.filename
        if not orig_filename or not allowed_file(orig_filename):
            errors.append(f"Skipped '{orig_filename}': Unsupported format.")
            continue

        ext = orig_filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex[:10]}_{secure_filename(orig_filename)}"
        file_path = os.path.join(Config.UPLOAD_FOLDER, unique_name)

        try:
            # Save file to disk
            file.save(file_path)
            file_size = os.path.getsize(file_path)

            # 2. Extract structured sections and generate chunks
            extraction, chunks = DocumentParserFactory.parse_and_chunk(
                file_path=file_path,
                company_name=company['name']
            )

            # 3. Register document in database
            doc_id = DocumentRepository.add_document(
                company_id=company_id,
                filename=unique_name,
                original_name=orig_filename,
                file_type=ext,
                file_path=file_path,
                file_size_bytes=file_size,
                total_pages_or_sections=extraction.total_pages_or_sections,
                chunk_count=len(chunks),
                status="indexed"
            )

            # Stamp document_id and clean original document name on chunks
            for c in chunks:
                c.document_id = doc_id
                c.document_name = orig_filename

            # 4. Ingest into Hybrid Vector + BM25 store
            hybrid_retriever.index_document_chunks(chunks)

            processed_docs.append({
                "id": doc_id,
                "filename": orig_filename,
                "file_type": ext,
                "chunks_indexed": len(chunks),
                "total_pages_or_sections": extraction.total_pages_or_sections
            })

        except Exception as e:
            logger.error(f"Failed to process '{orig_filename}': {e}")
            errors.append(f"Failed '{orig_filename}': {str(e)}")

    return jsonify({
        "success": len(processed_docs) > 0,
        "company": company,
        "processed_documents": processed_docs,
        "errors": errors
    })

@documents_bp.route('/documents/<int:doc_id>/download', methods=['GET'])
def download_document(doc_id: int):
    """Streams and downloads the original document file."""
    doc = DocumentRepository.get_by_id(doc_id)
    if not doc:
        return jsonify({"success": False, "message": "Document record not found."}), 404

    file_path = doc.get('file_path')
    if not file_path or not os.path.exists(file_path):
        alt_path = os.path.join(Config.UPLOAD_FOLDER, doc.get('filename', ''))
        if os.path.exists(alt_path):
            file_path = alt_path
        else:
            return jsonify({"success": False, "message": "Document file not found on server."}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=doc['original_name']
    )

@documents_bp.route('/documents/<int:doc_id>/rename', methods=['POST'])
def rename_document(doc_id: int):
    """Renames an uploaded document's display name."""
    data = request.get_json() or {}
    new_name = data.get('new_name', '').strip()
    if not new_name:
        return jsonify({"success": False, "message": "New document name cannot be empty."}), 400

    doc = DocumentRepository.get_by_id(doc_id)
    if not doc:
        return jsonify({"success": False, "message": "Document not found."}), 404

    # Ensure extension is retained if user didn't include it
    orig_ext = doc['file_type'].lower()
    if '.' not in new_name:
        new_name = f"{new_name}.{orig_ext}"

    success = DocumentRepository.rename(doc_id, new_name)
    if success:
        try:
            hybrid_retriever.rename_document(doc_id, new_name)
        except Exception as e:
            logger.warning(f"Failed to sync rename in retriever: {e}")
        return jsonify({"success": True, "message": "Document renamed successfully.", "new_name": new_name})
    return jsonify({"success": False, "message": "Failed to rename document."}), 500

@documents_bp.route('/documents/<int:doc_id>', methods=['DELETE', 'POST'])
@documents_bp.route('/documents/<int:doc_id>/delete', methods=['DELETE', 'POST'])
def delete_document(doc_id: int):
    """Deletes document record, purges search indices, and removes physical file from disk."""
    doc = DocumentRepository.get_by_id(doc_id)
    if not doc:
        # Idempotent deletion: document is already removed from database
        try:
            hybrid_retriever.remove_document(doc_id)
        except Exception:
            pass
        return jsonify({"success": True, "message": "Document is already removed."}), 200

    # Remove physical file if it exists
    file_path = doc.get('file_path')
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not remove physical file for doc {doc_id}: {e}")
    else:
        alt_path = os.path.join(Config.UPLOAD_FOLDER, doc.get('filename', ''))
        if os.path.exists(alt_path):
            try:
                os.remove(alt_path)
            except Exception as e:
                logger.warning(f"Could not remove alt file for doc {doc_id}: {e}")

    # Purge from FAISS & BM25
    try:
        hybrid_retriever.remove_document(doc_id)
    except Exception as e:
        logger.warning(f"Retriever removal warning for doc {doc_id}: {e}")

    success = DocumentRepository.delete(doc_id)
    if success:
        return jsonify({"success": True, "message": "Document deleted successfully."})
    return jsonify({"success": False, "message": "Failed to delete document."}), 500

