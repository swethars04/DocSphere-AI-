import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
from config import Config
from indexing.hybrid_retriever import HybridRetriever
from agents.planner import PlannerAgent
from agents.retriever import RetrievalAgent
from agents.reasoner import ReasoningAgent
from agents.verifier import VerificationAgent

from core.models import is_information_unavailable

logger = logging.getLogger(__name__)

class AgenticRAGPipeline:
    """
    Enterprise Self-Correcting Multi-Agent RAG Orchestrator.
    Manages Planner -> Hybrid Retrieval -> Multi-Turn Reasoner / Verifier Loop (max 3 cycles).
    """

    def __init__(self, hybrid_retriever: Optional[HybridRetriever] = None):
        self.api_key = Config.GROQ_API_KEY
        if not self.api_key or self.api_key.strip() == "":
            raise RuntimeError(
                "GROQ_API_KEY is not configured in your .env file. "
                "Please configure a valid API key to enable AI agent reasoning."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=Config.GROQ_API_BASE
        )

        self.hybrid_retriever = hybrid_retriever or HybridRetriever()
        self.planner = PlannerAgent(self.client)
        self.retriever = RetrievalAgent(self.hybrid_retriever)
        self.reasoner = ReasoningAgent(self.client)
        self.verifier = VerificationAgent(self.client)
        self.max_attempts = Config.MAX_VERIFICATION_ATTEMPTS

    def answer_query(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        company_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Executes end-to-end multi-agent self-correcting RAG query.
        """
        logger.info(f"Agentic RAG Pipeline executing for: '{question}' [Filter: {company_names}]")

        # 1. PLANNER AGENT: Decompose query into sub-queries
        try:
            plan = self.planner.create_plan(question, chat_history, company_names)
            sub_queries = plan.get("sub_queries", [question])
            plan_reasoning = plan.get("reasoning", "")
        except Exception as e:
            logger.error(f"Planning failed, falling back to raw question: {e}")
            sub_queries = [question]
            plan_reasoning = "Planning fallback."

        # 2. RETRIEVAL AGENT: Hybrid Vector + BM25 search & deduplication
        retrieved_results = self.retriever.retrieve_and_deduplicate(
            sub_queries=sub_queries,
            company_names=company_names,
            top_k=Config.TOP_K_RETRIEVAL
        )

        from db.repositories import DocumentRepository
        try:
            active_docs = DocumentRepository.get_all()
            if company_names:
                active_docs = [d for d in active_docs if d.get('company_name') in company_names]
        except Exception as e:
            logger.warning(f"Could not load active documents for pipeline catalog: {e}")
            active_docs = []

        catalog_lines = [
            f"- Document: {d['original_name']} | Organization: {d.get('company_name', 'General')} | Format: {d.get('file_type', '').upper()} | Total Chunks: {d.get('chunk_count', 0)}"
            for d in active_docs
        ]
        doc_catalog_text = f"Total Stored Documents: {len(active_docs)}\n" + ("\n".join(catalog_lines) if catalog_lines else "No documents uploaded.")

        # Detect if user is asking an inventory / catalog question
        catalog_query_patterns = [
            "how many doc", "how many file", "what are the current doc", "what are the doc",
            "list all doc", "list doc", "which doc", "available doc", "stored doc",
            "documents in this", "files in this", "current documents", "show documents",
            "what documents", "what files"
        ]
        is_catalog_query = any(p in question.lower() for p in catalog_query_patterns)

        if not retrieved_results:
            if is_catalog_query and active_docs:
                logger.info("Direct catalog query with no text chunks retrieved; proceeding with active document catalog.")
            else:
                target_str = f" for '{', '.join(company_names)}'" if company_names else ""
                return {
                    "answer": f"Information not available in the selected documents{target_str}. Please verify that relevant documents have been uploaded and selected.",
                    "confidence": "Low",
                    "reasoning": "Zero matching passages retrieved from the vector and lexical index.",
                    "citations": [],
                    "attempts": 1
                }

        passages_str = self.retriever.format_context_for_prompt(retrieved_results)
        context_str = f"[ACTIVE DOCUMENT REPOSITORY CATALOG]\n{doc_catalog_text}\n\n[RETRIEVED CONTENT PASSAGES]\n{passages_str}"

        # 3. REASONER & VERIFIER: Self-Correction Loop (max 3 cycles)
        correction_critique = None
        final_answer = ""
        final_confidence = "Medium"
        audit_summary = ""
        final_citations = []
        actual_attempts = 0

        for attempt in range(1, self.max_attempts + 1):
            actual_attempts = attempt
            logger.info(f"--- Self-Correction Loop: Attempt {attempt} of {self.max_attempts} ---")

            # Reasoner drafts answer
            draft = self.reasoner.generate_draft(
                question=question,
                context_str=context_str,
                chat_history=chat_history,
                correction_critique=correction_critique,
                retrieved_results=retrieved_results
            )
            final_answer = draft

            # If the draft states that information is not available, terminate immediately with no fake citations
            if is_information_unavailable(draft):
                logger.info("Draft determined information is unavailable in documents.")
                final_confidence = "Low"
                final_citations = []
                audit_summary = "Correctly verified that information is absent from indexed documents."
                break

            # Verifier audits draft against retrieved evidence and catalog
            verification = self.verifier.verify_and_audit(
                question=question,
                draft=draft,
                retrieved_results=retrieved_results,
                doc_catalog_text=doc_catalog_text
            )

            is_valid = verification.get("is_valid", False)
            final_confidence = verification.get("confidence", "Medium")
            audit_summary = verification.get("audit_reasoning", "")
            final_citations = verification.get("citations", [])

            if is_valid:
                logger.info(f"Draft PASSED verification audit on attempt {attempt}.")
                break
            else:
                critique = verification.get("critique", "Inconsistencies detected.")
                logger.warning(f"Draft FAILED audit on attempt {attempt}. Critique: {critique}")
                correction_critique = critique

        # Enforce safety rule: strictly clear citations and set Low confidence if info unavailable
        if is_information_unavailable(final_answer):
            final_citations = []
            final_confidence = "Low"
        elif is_catalog_query and active_docs:
            final_confidence = "High"
            # Filter out non-document pseudo citations like CATALOG
            final_citations = [
                c for c in final_citations
                if "CATALOG" not in c.get("document_name", "").upper()
            ]
            existing_doc_names = {c.get("document_name") for c in final_citations}
            for d in active_docs:
                if d['original_name'] not in existing_doc_names:
                    final_citations.append({
                        "document_name": d['original_name'],
                        "company_name": d.get('company_name', 'General'),
                        "page_or_section": "Document Storage",
                        "excerpt": f"Active repository document (ID #{d['id']}), {d.get('chunk_count', 0)} chunks indexed."
                    })
        elif not final_citations and retrieved_results and len(final_answer) > 80:
            # Fallback ONLY if the answer actually references sources or document names
            has_reference = any(
                r.chunk.document_name.lower() in final_answer.lower() or
                "[source" in final_answer.lower() or
                "[doc" in final_answer.lower()
                for r in retrieved_results[:3]
            )
            if has_reference:
                for r in retrieved_results[:3]:
                    final_citations.append({
                        "document_name": r.chunk.document_name,
                        "company_name": r.chunk.company_name,
                        "page_or_section": r.chunk.page_or_section,
                        "excerpt": r.chunk.text[:120] + "..."
                    })

        return {
            "answer": final_answer,
            "confidence": final_confidence,
            "reasoning": f"Plan: {plan_reasoning} | Audit: {audit_summary}",
            "citations": final_citations,
            "attempts": actual_attempts,
            "sub_queries": sub_queries
        }
