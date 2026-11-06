import json
import logging
from typing import List, Dict, Any, Optional
from config import Config

logger = logging.getLogger(__name__)

class PlannerAgent:
    """
    Planner Agent analyzes user queries, past conversation memory, and company filters
    to decompose complex multi-faceted questions into targeted retrieval sub-queries.
    """

    def __init__(self, client):
        self.client = client

    @property
    def model(self):
        return Config.GROQ_CHAT_MODEL

    def create_plan(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        company_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        logger.info(f"Planner Agent analyzing query: '{question}' (Companies: {company_names})")

        # Compile recent chat history
        history_str = ""
        if chat_history:
            for msg in chat_history[-4:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_str += f"{role}: {msg.get('content', '')}\n"

        company_context = f"Selected Companies: {', '.join(company_names)}" if company_names else "All available companies"

        system_prompt = f"""You are the Planner Agent for DocSphere AI, an enterprise multi-document intelligence platform.
Your task is to analyze the user's question, the recent conversation history, and the active company filter ({company_context}).
Break down the question into 1 to 3 targeted, focused search sub-queries optimized for hybrid vector and lexical retrieval.

Rules:
1. For simple or factual questions, produce 1 targeted sub-query.
2. For comparative or multi-metric queries (e.g., comparing metrics between companies or years), produce 2 to 3 distinct sub-queries covering each dimension.
3. Include relevant domain keywords, metrics, or company names where appropriate.

Output ONLY a valid JSON object matching this schema:
{{
  "sub_queries": ["query 1", "query 2"],
  "reasoning": "brief explanation of decomposition strategy"
}}
Do NOT output markdown blocks or extra commentary.
"""

        user_content = f"Question: {question}\n"
        if history_str:
            user_content += f"Conversation Context:\n{history_str}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.1,
                max_tokens=400,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            logger.info(f"Planner Agent generated plan: {result}")
            if not result.get("sub_queries"):
                result["sub_queries"] = [question]
            return result

        except Exception as e:
            logger.warning(f"Planner Agent primary model failed: {e}. Trying fallback...")
            try:
                response = self.client.chat.completions.create(
                    model=getattr(Config, 'FALLBACK_CHAT_MODEL', 'openai/gpt-oss-20b'),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.1,
                    max_tokens=400,
                    response_format={"type": "json_object"}
                )
                result = json.loads(response.choices[0].message.content)
                if not result.get("sub_queries"):
                    result["sub_queries"] = [question]
                return result
            except Exception as fb_err:
                logger.error(f"Planner fallback also failed: {fb_err}. Falling back to expanded query.")
                fallback_queries = self._expand_and_normalize_query(question)
                return {
                    "sub_queries": fallback_queries,
                    "reasoning": f"Smart domain expansion fallback: {fallback_queries}"
                }

    @staticmethod
    def _expand_and_normalize_query(question: str) -> List[str]:
        """Normalizes and expands queries with domain synonyms if LLM planning is unavailable."""
        import re
        clean_q = re.sub(r'^(give|tell|show|what is|what are|explain|can you|find|please)\s+(me\s+)?(the\s+)?', '', question.strip(), flags=re.IGNORECASE)
        clean_q = re.sub(r'\s+(from\s+the\s+pdf|in\s+the\s+pdf|from\s+document|in\s+document|from\s+pdf)\s*$', '', clean_q, flags=re.IGNORECASE).strip()
        
        q_lower = clean_q.lower()
        sub_queries = [clean_q] if clean_q else [question]

        # Domain expansions for competitive exams, study materials, and compliance
        if re.search(r'\b(math|maths|mathematics|arithmetic)\b', q_lower):
            sub_queries.append("Aptitude and Mental Ability mathematics")
            sub_queries.append("Simplification HCF LCM percentage ratio interest")
        elif re.search(r'\b(reasoning|mental ability|aptitude)\b', q_lower):
            sub_queries.append("Aptitude and Mental Ability reasoning puzzles number series")
        elif re.search(r'\b(english|grammar)\b', q_lower):
            sub_queries.append("General English grammar vocabulary writing skills")
        elif re.search(r'\b(tamil)\b', q_lower):
            sub_queries.append("பொதுத்தமிழ் தமிழ் இலக்கியம்")

        return list(dict.fromkeys(sub_queries))[:3]
