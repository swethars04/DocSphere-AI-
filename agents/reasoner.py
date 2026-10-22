import logging
from typing import List, Dict, Any, Optional
from config import Config
from core.models import RetrievalResult

logger = logging.getLogger(__name__)

class ReasoningAgent:
    """
    Reasoning Agent synthesizes grounded, audit-ready responses strictly derived
    from retrieved evidence chunks. Incorporates verification feedback in self-correcting loops.
    """

    def __init__(self, client):
        self.client = client

    @property
    def model(self):
        return Config.GROQ_CHAT_MODEL

    def generate_draft(
        self,
        question: str,
        context_str: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        correction_critique: Optional[str] = None,
        retrieved_results: Optional[List[RetrievalResult]] = None
    ) -> str:
        logger.info("Reasoning Agent generating response draft...")

        # Compile recent conversation history
        history_str = ""
        if chat_history:
            for msg in chat_history[-4:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_str += f"{role}: {msg.get('content', '')}\n"

        system_prompt = """You are the Reasoning Agent for DocSphere AI, an enterprise-grade document intelligence platform.
Your sole mission is to generate highly accurate, factually grounded answers based EXCLUSIVELY on the provided retrieved context.

STRICT INSTRUCTIONS:
1. ONLY use information explicitly stated in the [Source #N] blocks or the [ACTIVE DOCUMENT REPOSITORY CATALOG]. DO NOT assume, extrapolate, or use outside knowledge.
2. If the user asks about the count, list, or names of documents/files currently stored in the system (e.g. "how many documents", "what are the current documents in this?", "list all files"), use the [ACTIVE DOCUMENT REPOSITORY CATALOG] to provide the complete, authoritative list and count of all active documents in Document Storage.
3. If specific content/factual questions cannot be answered from the provided sources, state clearly: "Information not available in the selected documents."
4. Every factual statement, statistic, metric, or policy MUST cite its source using the exact format: [Doc: <DocumentName>, Location: <Location>] or [Source #N].
5. Format your response cleanly using GitHub-flavored markdown: bold key metrics, use bullet points, and render tabular data where helpful.
6. If a Verification Critique is provided, you MUST correct the exact inaccuracies, hallucinations, or missing citations pointed out in the critique.
7. Completeness: Ensure all requested topics, numbered sections, and bullet points are comprehensively and fully written out. Never cut off abruptly or leave unfinished sentences or blank bullet points.
"""

        user_content = f"Question: {question}\n\n"
        if history_str:
            user_content += f"Prior Conversation:\n{history_str}\n\n"

        user_content += f"Retrieved Context:\n{context_str}\n\n"

        if correction_critique:
            user_content += (
                f"CRITICAL AUDIT FEEDBACK FROM VERIFICATION AGENT:\n"
                f"{correction_critique}\n\n"
                f"Please regenerate your answer now, fixing all identified deficiencies."
            )

        import time
        max_gen_tokens = getattr(Config, 'MAX_GENERATION_TOKENS', 2048)

        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.1,
                    max_tokens=max_gen_tokens
                )
                choice = response.choices[0]
                draft = choice.message.content.strip()

                # If the generation stopped due to token limit length, request seamless continuation
                if choice.finish_reason == "length":
                    logger.warning("Reasoning Agent response hit token length limit. Requesting seamless continuation to complete all sections...")
                    try:
                        continuation_response = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_content},
                                {"role": "assistant", "content": draft},
                                {"role": "user", "content": "Please continue and complete the remaining sections and points from where you left off. Do not repeat already completed sections; start directly with the continuation."}
                            ],
                            temperature=0.1,
                            max_tokens=1024
                        )
                        continuation_text = continuation_response.choices[0].message.content.strip()
                        draft = f"{draft}\n\n{continuation_text}".strip()
                    except Exception as cont_err:
                        logger.warning(f"Continuation request failed: {cont_err}")

                logger.info("Reasoning Agent completed full draft generation.")
                return draft

            except Exception as e:
                err_str = str(e)
                if "429" in err_str and attempt == 0:
                    logger.warning("Groq rate limit encountered in ReasoningAgent. Waiting 6 seconds before retry...")
                    time.sleep(6)
                    continue
                logger.error(f"Reasoning Agent error: {e}")
                if retrieved_results:
                    # Provide an immediate grounded summary rather than failing the request
                    top_text = "\n\n".join([r.chunk.text for r in retrieved_results[:2]])
                    return (
                        f"Based on the relevant excerpts from your documents:\n\n{top_text[:800]}...\n\n"
                        f"*(Information extracted directly from verified document records.)*"
                    )
                raise RuntimeError(f"Reasoning Agent failed: {str(e)}")
