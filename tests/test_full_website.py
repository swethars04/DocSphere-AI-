import os
import io
import json
import unittest
import pymupdf
from PIL import Image, ImageDraw

from app import create_app
from config import Config
from db.database import get_db_connection, init_db
from db.repositories import DocumentRepository, ChatRepository, CompanyRepository
from core.models import is_information_unavailable
from core.parsers.base_parser import BaseParser
from core.parsers.pdf_parser import PDFParser
from api.routes_chat import generate_relevant_chat_title


class DocuSphereFullWebsiteTestCase(unittest.TestCase):
    """
    Comprehensive End-to-End Test Suite for DocuSphere AI.
    Tests all UI routes, API endpoints, Document Ingestion, OCR Fallback,
    Document Storage management (Rename/Download/Delete), and Chat workflows.
    """

    @classmethod
    def setUpClass(cls):
        # Configure test Flask client
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Ensure database is initialized
        init_db()

        # Temporary files to clean up
        cls.temp_files = []

    @classmethod
    def tearDownClass(cls):
        # Clean up temporary test files
        for path in cls.temp_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        # Clean up test company so test data never pollutes application database
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM companies WHERE name = ?", ("Acme Global Test",))
                conn.commit()
        except Exception:
            pass

    # ==========================================
    # 1. FRONTEND ROUTE RENDERING TESTS
    # ==========================================

    def test_01_homepage_renders(self):
        """Verify the main Ingestion / Dashboard portal loads properly."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertTrue("DocSphere AI" in html or "DocuSphere AI" in html)
        self.assertIn("Ingested Document Knowledge Bases", html)
        self.assertIn("Upload", html)

    def test_02_documents_page_renders(self):
        """Verify the dedicated Document Storage management tab loads properly."""
        response = self.client.get('/documents')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Document Storage", html)
        self.assertIn("Search by document name", html)

    def test_03_chat_page_renders(self):
        """Verify the Multi-Agent RAG Chat workspace loads properly via redirect."""
        # /chat redirects to /chat/<session_id>
        response = self.client.get('/chat', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertTrue("DocSphere AI" in html or "DocuSphere AI" in html)
        self.assertIn("conversations", html.lower())

    def test_04_custom_404_handler(self):
        """Verify 404 handler returns graceful error response for missing routes."""
        response = self.client.get('/api/invalid-nonexistent-endpoint')
        self.assertEqual(response.status_code, 404)

    # ==========================================
    # 2. COMPANY MANAGEMENT API TESTS
    # ==========================================

    def test_05_company_creation_and_listing(self):
        """Verify creating and fetching organizations via API."""
        payload = {
            "name": "Acme Global Test",
            "sector": "Technology",
            "ticker": "AGL"
        }
        res = self.client.post('/api/companies', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["company"]["name"], "Acme Global Test")

        # Fetch all companies
        list_res = self.client.get('/api/companies')
        self.assertEqual(list_res.status_code, 200)
        list_data = list_res.get_json()
        self.assertTrue(list_data.get("success"))
        names = [c["name"] for c in list_data.get("companies", [])]
        self.assertIn("Acme Global Test", names)

    # ==========================================
    # 3. TEXT & DIGITAL PDF EXTRACTION & UPLOAD
    # ==========================================

    def test_06_text_document_upload_and_indexing(self):
        """Verify uploading, parsing, chunking, and indexing a text document."""
        sample_content = (
            "Acme Global posted record revenue of $100 Million for fiscal year 2026. "
            "Net operating profit margin increased by 18 percent year-over-year."
        )
        data = {
            'company_name': 'Acme Global Test',
            'files': (io.BytesIO(sample_content.encode('utf-8')), 'acme_financials.txt')
        }
        res = self.client.post(
            '/api/documents/upload',
            data=data,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("success"))
        docs = res_json.get("processed_documents", [])
        self.assertGreater(len(docs), 0)
        self.assertEqual(docs[0]["filename"], "acme_financials.txt")
        self.assertGreater(docs[0]["chunks_indexed"], 0)

        # Immediately clean up the test document so it does not persist in the UI
        del_res = self.client.post(f'/api/documents/{docs[0]["id"]}/delete')
        self.assertEqual(del_res.status_code, 200)

    def test_07_digital_pdf_parsing_zero_ocr_overhead(self):
        """Verify standard digital PDF parses fast with native fitz and ocr=False."""
        pdf_path = os.path.join(Config.UPLOAD_FOLDER, "test_digital_spec.pdf")
        self.temp_files.append(pdf_path)

        doc = pymupdf.open()
        page = doc.new_page(width=500, height=400)
        page.insert_text((50, 100), "Standard Digital Document with selectable fonts.", fontsize=14)
        doc.save(pdf_path)
        doc.close()

        parser = PDFParser()
        result = parser.parse(pdf_path)
        self.assertGreater(len(result.sections), 0)
        self.assertEqual(result.sections[0].metadata.get("ocr"), False)
        self.assertIn("Standard Digital Document", result.sections[0].text)

    # ==========================================
    # 4. SCANNED / IMAGE-ONLY PDF OCR FALLBACK
    # ==========================================

    def test_08_scanned_pdf_ocr_fallback(self):
        """Verify scanned / image-only PDF engages RapidOCR fallback and extracts text."""
        # 1. Render text into a pure raster bitmap (no digital text)
        img = Image.new('RGB', (600, 200), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((30, 80), "Confidential Audit Verification 2026", fill=(0, 0, 0))

        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format='PNG')
        img_bytes = img_bytes_io.getvalue()

        # 2. Embed bitmap into PDF
        pdf_path = os.path.join(Config.UPLOAD_FOLDER, "test_scanned_ocr.pdf")
        self.temp_files.append(pdf_path)

        doc_scan = pymupdf.open()
        page_scan = doc_scan.new_page(width=600, height=200)
        page_scan.insert_image(page_scan.rect, stream=img_bytes)
        doc_scan.save(pdf_path)
        doc_scan.close()

        # 3. Parse with PDFParser
        parser = PDFParser()
        result = parser.parse(pdf_path)
        self.assertGreater(len(result.sections), 0)
        section = result.sections[0]
        self.assertEqual(section.metadata.get("ocr"), True)
        self.assertTrue(
            "Confidential" in section.text or "Audit" in section.text or "Verification" in section.text,
            f"Expected OCR to detect text, got: {section.text}"
        )

    # ==========================================
    # 5. DOCUMENT STORAGE TAB (RENAME, DOWNLOAD, DELETE)
    # ==========================================

    def test_09_document_storage_management_lifecycle(self):
        """Verify full lifecycle in Document Storage tab: List -> Rename -> Download -> Delete."""
        # 1. Upload a dedicated document for lifecycle testing
        sample_doc = (
            "Board of Directors approved expansion into renewable energy. "
            "Capital expenditure is projected at $45 Million."
        )
        data = {
            'company_name': 'Acme Global Test',
            'files': (io.BytesIO(sample_doc.encode('utf-8')), 'board_resolution.txt')
        }
        res_upload = self.client.post('/api/documents/upload', data=data, content_type='multipart/form-data')
        self.assertEqual(res_upload.status_code, 200)
        doc_info = res_upload.get_json()["processed_documents"][0]
        doc_id = doc_info["id"]

        # 2. List documents
        res_list = self.client.get('/api/documents')
        self.assertEqual(res_list.status_code, 200)
        all_docs = res_list.get_json()["documents"]
        doc_ids = [d["id"] for d in all_docs]
        self.assertIn(doc_id, doc_ids)

        # 3. Rename document
        rename_payload = {"new_name": "board_resolution_2026_approved.txt"}
        res_rename = self.client.post(f'/api/documents/{doc_id}/rename', json=rename_payload)
        self.assertEqual(res_rename.status_code, 200)
        self.assertEqual(res_rename.get_json()["new_name"], "board_resolution_2026_approved.txt")

        # Verify rename in DB
        updated_doc = DocumentRepository.get_by_id(doc_id)
        self.assertEqual(updated_doc["original_name"], "board_resolution_2026_approved.txt")

        # 4. Download document
        res_dl = self.client.get(f'/api/documents/{doc_id}/download')
        self.assertEqual(res_dl.status_code, 200)
        self.assertIn("attachment", res_dl.headers.get("Content-Disposition", ""))

        # 5. Delete document
        res_del = self.client.post(f'/api/documents/{doc_id}/delete')
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

        # Verify document is removed from DB
        deleted_check = DocumentRepository.get_by_id(doc_id)
        self.assertIsNone(deleted_check)

        # 6. Idempotent delete (calling delete again must not fail with 500)
        res_del_again = self.client.post(f'/api/documents/{doc_id}/delete')
        self.assertEqual(res_del_again.status_code, 200)

    # ==========================================
    # 6. CHAT SESSION & MULTI-AGENT RAG WORKFLOW
    # ==========================================

    def test_10_chat_session_creation_and_autotitle(self):
        """Verify chat session creation, relevant title generation, and renaming."""
        # 1. Create chat session
        res_create = self.client.post('/api/chat/sessions', json={})
        self.assertEqual(res_create.status_code, 200)
        session_data = res_create.get_json()["session"]
        session_id = session_data["session_id"]
        self.assertTrue(session_data["title"].startswith("Chat #"))

        # 2. Test dynamic auto-title algorithm
        title1 = generate_relevant_chat_title("What are the key financial risks in 2026?")
        self.assertEqual(title1, "Key Financial Risks In 2026")

        title2 = generate_relevant_chat_title("How to make a coffee?")
        self.assertIn("Coffee", title2)

        # 3. Rename session
        res_rename = self.client.post(f'/api/chat/sessions/{session_id}/rename', json={"title": "Q1 Audit Review"})
        self.assertEqual(res_rename.status_code, 200)
        self.assertEqual(res_rename.get_json()["new_title"], "Q1 Audit Review")

        # 4. Delete session
        res_delete = self.client.delete(f'/api/chat/sessions/{session_id}')
        self.assertEqual(res_delete.status_code, 200)
        self.assertTrue(res_delete.get_json()["success"])

    def test_11_verifier_gate_avoids_bogus_citations_on_irrelevant_questions(self):
        """Verify is_information_unavailable correctly flags absent info to prevent false citations."""
        # Queries that state information is not in the documents
        self.assertTrue(is_information_unavailable("The requested information is not available in the selected documents."))
        self.assertTrue(is_information_unavailable("No information provided regarding how to prepare coffee."))
        self.assertTrue(is_information_unavailable("This document does not contain information about recipes."))

        # Legitimate answers should NOT be flagged as unavailable
        self.assertFalse(is_information_unavailable("Acme Global generated $100 Million in revenue during fiscal 2026."))

    # ==========================================
    # 7. BASE PARSER SANITIZATION
    # ==========================================

    def test_12_base_parser_sanitization(self):
        """Verify text sanitizer strips control characters, excessive whitespace, and tabs."""
        raw = "Line 1\t\twith   extra   spaces.\n\n\n\nLine 2\xa0non-breaking."
        cleaned = BaseParser.clean_text(raw)
        self.assertEqual(cleaned, "Line 1 with extra spaces.\n\nLine 2 non-breaking.")


if __name__ == '__main__':
    unittest.main()
