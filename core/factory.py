import os
import logging
from typing import Tuple, List, Optional
from config import Config
from core.models import ExtractionResult, DocumentChunk
from core.parsers.base_parser import BaseParser
from core.parsers.pdf_parser import PDFParser
from core.parsers.docx_parser import DocxParser
from core.parsers.xbrl_parser import XBRLParser
from core.parsers.text_html_parser import TextHTMLParser
from core.chunker import SemanticChunker

logger = logging.getLogger(__name__)

class DocumentParserFactory:
    """
    Factory for resolving format-specific document parsers and executing
    clean extraction and semantic chunking.
    """

    @staticmethod
    def get_parser(file_path: str) -> BaseParser:
        """Determines the appropriate parser based on file extension and signatures."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Target document not found at: {file_path}")

        filename = os.path.basename(file_path).lower()
        ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''

        if ext == 'pdf':
            return PDFParser()
        elif ext in {'docx', 'doc'}:
            return DocxParser()
        elif ext in {'xml', 'xbrl'}:
            return XBRLParser()
        elif ext in {'html', 'htm', 'txt', 'md'}:
            return TextHTMLParser()
        else:
            logger.warning(f"Unrecognized extension '{ext}', defaulting to TextHTMLParser.")
            return TextHTMLParser()

    @classmethod
    def parse_and_chunk(
        cls,
        file_path: str,
        company_name: str,
        document_id: Optional[int] = None
    ) -> Tuple[ExtractionResult, List[DocumentChunk]]:
        """
        High-level pipeline:
        1. Selects parser and extracts structured document sections.
        2. Applies semantic chunker with company and location metadata.
        """
        parser = cls.get_parser(file_path)
        logger.info(f"Using {parser.__class__.__name__} for file: {file_path}")

        # 1. Extraction
        extraction = parser.parse(file_path)

        # 2. Chunking
        chunker = SemanticChunker()
        chunks = chunker.chunk_extraction_result(
            extraction=extraction,
            company_name=company_name,
            document_id=document_id
        )

        logger.info(f"Successfully generated {len(chunks)} chunks for '{extraction.filename}' [{company_name}]")
        return extraction, chunks
