import os
import logging
from typing import List, Optional
from core.models import ExtractionResult, RawExtractedSection
from core.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

# Lazy singleton for OCR engine so it loads into memory only if an image-based or scanned page is encountered
_ocr_engine = None

def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR(use_cls=False)
            logger.info("RapidOCR engine initialized successfully for PDF fallback extraction.")
        except Exception as e:
            logger.warning(f"Could not initialize RapidOCR engine: {e}")
            _ocr_engine = False
    return _ocr_engine if _ocr_engine is not False else None


class PDFParser(BaseParser):
    """Extracts text from PDF documents page by page using PyMuPDF (fitz) with RapidOCR fallback."""

    def _ocr_page(self, page) -> Optional[str]:
        """Performs local OCR on a PyMuPDF page rendered as an image when digital text is absent or negligible."""
        ocr = _get_ocr_engine()
        if not ocr:
            return None
        try:
            import numpy as np
            # 110 DPI with raw memory buffer and use_cls=False delivers high OCR accuracy with 3-4x faster throughput
            pix = page.get_pixmap(dpi=110)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.h, pix.w, pix.n))
            if pix.n == 4:
                arr = arr[:, :, :3]
            result, _ = ocr(arr, use_cls=False)
            if not result:
                return None
            lines = [item[1] for item in result if item and len(item) > 1 and item[1]]
            ocr_text = "\n".join(lines)
            return self.clean_text(ocr_text)
        except Exception as e:
            logger.warning(f"RapidOCR fallback extraction failed on page: {e}")
            return None

    def parse(self, file_path: str) -> ExtractionResult:
        filename = os.path.basename(file_path)
        sections: List[RawExtractedSection] = []
        total_pages = 0

        # Attempt extraction using PyMuPDF (fitz)
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            total_pages = len(doc)
            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                raw_text = page.get_text("text")
                cleaned = self.clean_text(raw_text)

                # Fast path: Native digital text check (>= 10 characters)
                if cleaned and len(cleaned) >= 10:
                    sections.append(
                        RawExtractedSection(
                            text=cleaned,
                            page_or_section=f"Page {page_num + 1}",
                            metadata={"page_number": page_num + 1, "ocr": False}
                        )
                    )
                elif len(page.get_images()) > 0:
                    # Fallback path: Only run OCR if page contains embedded images (scanned page)
                    ocr_text = self._ocr_page(page)
                    if ocr_text and len(ocr_text) > len(cleaned or ""):
                        logger.info(
                            f"Page {page_num + 1} of '{filename}' extracted via RapidOCR fallback "
                            f"({len(ocr_text)} characters)."
                        )
                        sections.append(
                            RawExtractedSection(
                                text=ocr_text,
                                page_or_section=f"Page {page_num + 1}",
                                metadata={"page_number": page_num + 1, "ocr": True}
                            )
                        )
                    elif cleaned:
                        sections.append(
                            RawExtractedSection(
                                text=cleaned,
                                page_or_section=f"Page {page_num + 1}",
                                metadata={"page_number": page_num + 1, "ocr": False}
                            )
                        )
                elif cleaned:
                    # Minimal native text on image-free page
                    sections.append(
                        RawExtractedSection(
                            text=cleaned,
                            page_or_section=f"Page {page_num + 1}",
                            metadata={"page_number": page_num + 1, "ocr": False}
                        )
                    )

            doc.close()
            logger.info(f"PyMuPDF parsed {len(sections)} pages from: {filename}")
        except ImportError:
            logger.warning("PyMuPDF not installed, attempting fallback to pypdf...")
            try:
                import pypdf  # type: ignore
                reader = pypdf.PdfReader(file_path)
                total_pages = len(reader.pages)
                for page_num, page in enumerate(reader.pages):
                    raw_text = page.extract_text() or ""
                    cleaned = self.clean_text(raw_text)
                    if cleaned:
                        sections.append(
                            RawExtractedSection(
                                text=cleaned,
                                page_or_section=f"Page {page_num + 1}",
                                metadata={"page_number": page_num + 1, "ocr": False}
                            )
                        )
                logger.info(f"pypdf parsed {len(sections)} pages from: {filename}")
            except Exception as e:
                logger.error(f"Fallback PDF parsing failed for {filename}: {e}")
                raise RuntimeError(f"Failed to parse PDF {filename}: {str(e)}")
        except Exception as e:
            logger.error(f"PDF parsing error in {filename}: {e}")
            raise RuntimeError(f"Failed to parse PDF {filename}: {str(e)}")

        return ExtractionResult(
            filename=filename,
            file_type="pdf",
            total_pages_or_sections=max(total_pages, 1),
            sections=sections,
            metadata={"total_pages": total_pages}
        )

