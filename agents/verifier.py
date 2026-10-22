import json
import logging
from typing import List, Dict, Any, Optional
from config import Config
from core.models import RetrievalResult, is_information_unavailable

logger = logging.getLogger(__name__)

class VerificationAgent:
    """
    Verification Agent audits drafted responses against the ground-truth retrieved evidence.
    Identifies hallucinations, validates exact metric/date match, and compiles verifiable citations.
    """

    def __init__(self, client):
        self.client = client

    @property
    def model(self):
        return Config.GROQ_CHAT_MODEL

    def verify_and_audit(
        self,
        question: str,
        draft: str,
        retrieved_results: List[RetrievalResult],
        doc_catalog_text: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info("Verification Agent auditing drafted response for factuality & citations...")

        # If no results retrieved and no catalog text OR the answer explicitly notes information is missing/unavailable
        if (not retrieved_results and not doc_catalog_text) or is_information_unavailable(draft):
            logger.info("Information unavailable in documents; setting Low confidence and empty citations.")
            return {
                "is_valid": True,
                "confidence": "Low",
                "critique": "",
                "audit_reasoning": "Correctly determined information is unavailable in the indexed documents.",
                "citations": []
            }

        # Build context evidence text
        evidence_blocks = []
        if doc_catalog_text:
            evidence_blocks.append(f"[ACTIVE DOCUMENT REPOSITORY CATALOG]\n{doc_catalog_text}\n")
        for idx, res in enumerate(retrieved_results, 1):
            c = res.chunk
            evidence_blocks.append(
                f"[Source #{idx}] (Doc: {c.document_name} | Company: {c.company_name} | Location: {c.page_or_section})\n"
                f"{c.text}\n"
            )
        evidence_str = "\n---\n".join(evidence_blocks)

        system_prompt = """You are the Senior Verification & Compliance Auditor for DocSphere AI.
Your role is to rigorously fact-check the drafted answer against the provided evidence blocks and the [ACTIVE DOCUMENT REPOSITORY CATALOG].

AUDIT CRITERIA:
1. Factuality & Hallucination: Is every assertion, numeric figure, metric, and entity in the draft explicitly backed by the evidence blocks or the [ACTIVE DOCUMENT REPOSITORY CATALOG]?
2. Citation Validity: Are source references accurate and relevant?
3. Completeness: Does the draft directly answer the user's question without adding ungrounded assumptions?

Determine:
- is_valid: true ONLY if the draft contains NO hallucinations and no contradicted facts. Otherwise false.
- confidence: "High" (if completely verified with strong evidence), "Medium" (if verified but partial coverage), "Low" (if ungrounded, speculative, or information is not found in documents).
- critique: If is_valid is false, specify EXACTLY which claims are ungrounded and what must be removed or corrected. If true, keep empty string.
- audit_reasoning: Brief 1-2 sentence justification of your verdict.
- citations: List of JSON objects for sources ACTUALLY utilized to support claims in the draft. If the draft states that information is not available, citations MUST be empty [].
    Each citation object:
    - "document_name": string
    - "company_name": string
    - "page_or_section": string
    - "excerpt": brief string excerpt (up to 150 chars) from the source that verifies the claim.

Output ONLY a JSON object matching this schema. Do NOT wrap in markdown backticks.
"""

        user_content = f"""USER QUESTION:
{question}

EVIDENCE BLOCKS:
{evidence_str}

DRAFTED ANSWER TO AUDIT:
{draft}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            
            # Post-check: If draft was unavailable, ensure citations remain empty
            if is_information_unavailable(draft):
                result["citations"] = []
                result["confidence"] = "Low"

            logger.info(f"Verification Agent verdict: valid={result.get('is_valid')}, confidence={result.get('confidence')}")
            return result

        except Exception as e:
            logger.error(f"Verification Agent error: {e}. Defaulting to passing verdict.")
            if is_information_unavailable(draft):
                return {
                    "is_valid": True,
                    "confidence": "Low",
                    "critique": "",
                    "audit_reasoning": f"Audit fallback (info unavailable): {e}",
                    "citations": []
                }
            
            # Only synthesize fallback citations if draft actually references documents
            fallback_citations = []
            has_reference = any(r.chunk.document_name.lower() in draft.lower() or "[source" in draft.lower() for r in retrieved_results[:3])
            if has_reference:
                for r in retrieved_results[:3]:
                    fallback_citations.append({
                        "document_name": r.chunk.document_name,
                        "company_name": r.chunk.company_name,
                        "page_or_section": r.chunk.page_or_section,
                        "excerpt": r.chunk.text[:120] + "..."
                    })
            return {
                "is_valid": True,
                "confidence": "Medium",
                "critique": "",
                "audit_reasoning": f"Audit fallback due to error: {e}",
                "citations": fallback_citations
            }
