import logging
from flask import Flask, render_template
from config import Config
from db.database import init_db
from api.routes_frontend import frontend_bp
from api.routes_documents import documents_bp
from api.routes_chat import chat_bp

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_app():
    """Application factory for DocSphere AI."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize the relational SQLite schema
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Failed to initialize SQLite database: {e}")
        raise e

    # Register Blueprints
    app.register_blueprint(frontend_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(chat_bp)

    # Global Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('index.html', error_msg="The page you requested was not found."), 404

    # Warm up OCR engine asynchronously to prevent first-request cold-start latency
    import threading
    def _warmup():
        try:
            from core.parsers.pdf_parser import _get_ocr_engine
            _get_ocr_engine()
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()

    return app

if __name__ == '__main__':
    app = create_app()
    port = app.config.get('PORT', 5000)
    logger.info(f"Starting DocSphere AI platform on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=app.config.get('DEBUG', False))
