import os
import io
import json
import uuid
import unittest
import pymupdf
from PIL import Image, ImageDraw

from app import create_app
from config import Config
from db.database import get_db_connection, init_db
from db.repositories import DocumentRepository, ChatRepository, CompanyRepository, UserRepository
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

        # Authenticate default test client as Compliance Admin
        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_email'] = 'admin@docusphere.ai'
            sess['user_name'] = 'Compliance Admin'
            sess['user_role'] = 'admin'

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

    # ==========================================
    # 8. AUTHENTICATION & RBAC PERMISSION TESTS
    # ==========================================

    def test_13_unauthenticated_user_redirected_to_login(self):
        """Verify unauthenticated requests to protected endpoints redirect to /login."""
        anon_client = self.app.test_client()
        res = anon_client.get('/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

        # API calls receive 401 JSON
        api_res = anon_client.get('/api/documents')
        self.assertEqual(api_res.status_code, 401)
        self.assertFalse(api_res.get_json()['success'])

    def test_14_demo_login_and_persona_switch(self):
        """Verify 1-click demo login establishes authentic user sessions."""
        client = self.app.test_client()
        res = client.get('/demo-login/admin', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Check me endpoint
        me_res = client.get('/api/auth/me')
        self.assertEqual(me_res.status_code, 200)
        user_data = me_res.get_json()['user']
        self.assertEqual(user_data['email'], 'admin@docusphere.ai')
        self.assertEqual(user_data['role'], 'admin')

    def test_15_rbac_analyst_cannot_access_database_but_can_upload(self):
        """Verify Role-Based Access Control blocks Analyst from internal database while allowing document ingestion."""
        analyst_client = self.app.test_client()
        with analyst_client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['user_email'] = 'analyst@docusphere.ai'
            sess['user_role'] = 'analyst'

        # Analyst cannot view internal database inspector (returns 403)
        db_res = analyst_client.get('/database')
        self.assertEqual(db_res.status_code, 403)

        # Analyst CAN trigger document upload (authorized, returns 400 when empty files provided, not 403)
        upload_res = analyst_client.post('/api/documents/upload', data={})
        self.assertEqual(upload_res.status_code, 400)
        self.assertIn("No files provided", upload_res.get_json()['message'])

    def test_16_admin_passcode_registration_security(self):
        """Verify registration flow enforces least privilege and requires secret passcode for admin role."""
        test_client = self.app.test_client()
        unique_suffix = uuid.uuid4().hex[:6]
        email_analyst = f"analyst_{unique_suffix}@example.com"
        email_invalid = f"hacker_{unique_suffix}@example.com"
        email_admin = f"admin_{unique_suffix}@example.com"

        # 1. Blank passcode -> defaults to analyst
        res_analyst = test_client.post('/register', json={
            "full_name": "Test Analyst User",
            "email": email_analyst,
            "password": "securepassword123",
            "admin_code": ""
        })
        self.assertEqual(res_analyst.status_code, 200)
        self.assertEqual(res_analyst.get_json()["user"]["role"], "analyst")

        # 2. Invalid passcode -> rejected with 400 error
        res_invalid = test_client.post('/register', json={
            "full_name": "Hacker Attempt",
            "email": email_invalid,
            "password": "securepassword123",
            "admin_code": "wrong_guess_code"
        })
        self.assertEqual(res_invalid.status_code, 400)
        self.assertIn("Invalid Admin Security Passcode", res_invalid.get_json()["message"])

        # 3. Valid passcode -> correctly grants admin role
        res_admin = test_client.post('/register', json={
            "full_name": "New Compliance Admin",
            "email": email_admin,
            "password": "securepassword123",
            "admin_code": Config.ADMIN_INVITE_CODE
        })
        self.assertEqual(res_admin.status_code, 200)
        self.assertEqual(res_admin.get_json()["user"]["role"], "admin")

    def test_17_profile_update_and_password_change(self):
        """Verify user profile editing and password updates."""
        client = self.app.test_client()
        profile_email = f"profile_{uuid.uuid4().hex[:6]}@example.com"
        # Register a test user
        client.post('/register', json={
            "full_name": "Profile Tester",
            "email": profile_email,
            "password": "initialpassword123"
        })

        # 1. View /profile
        res_profile = client.get('/profile')
        self.assertEqual(res_profile.status_code, 200)
        self.assertIn("Account & Security Settings", res_profile.get_data(as_text=True))

        # 2. Update profile name & avatar color
        res_update = client.post('/api/user/profile', json={
            "full_name": "Profile Tester Updated",
            "avatar_color": "#8b5cf6"
        })
        self.assertEqual(res_update.status_code, 200)
        self.assertTrue(res_update.get_json()["success"])

        # 3. Password update failure with incorrect current password
        res_pw_fail = client.post('/api/user/password', json={
            "current_password": "wrongpassword",
            "new_password": "brandnewpassword123"
        })
        self.assertEqual(res_pw_fail.status_code, 400)

        # 4. Password update success
        res_pw_ok = client.post('/api/user/password', json={
            "current_password": "initialpassword123",
            "new_password": "brandnewpassword123"
        })
        self.assertEqual(res_pw_ok.status_code, 200)
        self.assertTrue(res_pw_ok.get_json()["success"])

    def test_18_user_account_deletion_and_master_admin_lock(self):
        """Verify user account self-deletion, admin user deletion, and Master Admin protection lock."""
        # 1. Master Admin (ID 1) CANNOT be deleted
        admin_client = self.app.test_client()
        with admin_client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_email'] = 'admin@docusphere.ai'
            sess['user_role'] = 'admin'
        res_lock = admin_client.post('/api/user/delete', json={"password": "adminpassword123"})
        self.assertEqual(res_lock.status_code, 403)
        self.assertIn("protected", res_lock.get_json()["message"])

        # 2. Regular user self-deletion
        user_client = self.app.test_client()
        del_email = f"delete_{uuid.uuid4().hex[:6]}@example.com"
        user_client.post('/register', json={
            "full_name": "Delete Me User",
            "email": del_email,
            "password": "password123"
        })
        # Self-delete with correct password
        res_del = user_client.post('/api/user/delete', json={"password": "password123"})
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

        # Verify user is gone
        self.assertIsNone(UserRepository.get_by_email(del_email))

        # 3. Admin deleting another user via /api/users/<id>
        other_client = self.app.test_client()
        target_email = f"target_{uuid.uuid4().hex[:6]}@example.com"
        created = other_client.post('/register', json={
            "full_name": "Admin Target",
            "email": target_email,
            "password": "password123"
        })
        target_uid = created.get_json()["user"]["id"]

        res_admin_del = admin_client.delete(f'/api/users/{target_uid}')
        self.assertEqual(res_admin_del.status_code, 200)
        self.assertTrue(res_admin_del.get_json()["success"])
        self.assertIsNone(UserRepository.get_by_id(target_uid))


if __name__ == '__main__':
    unittest.main()
