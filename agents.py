import json
import logging
from openai import OpenAI
from config import Config

logger = logging.getLogger(__name__)

class PlannerAgent:
    """
    Planner Agent analyzes user queries and past conversation history
    to design a search strategy and decompose the queries into sub-queries.
    """
    def __init__(self, client):
        self.client = client
        self.model = Config.GROQ_CHAT_MODEL

    def create_plan(self, question, chat_history=None):
        logger.info("Planner Agent analyzing query and historical context...")
        
        # Compile chat history to string
        history_str = ""
        if chat_history:
            for msg in chat_history[-4:]:
                role = "User" if msg['role'] == 'user' else "Assistant"
                history_str += f"{role}: {msg['content']}\n"
        
        system_prompt = """You are the Planner Agent for a Sustainability Report RAG system.
Your job is to analyze the user's question and past conversation history, then break it down into search sub-queries.
If the query is simple, generate 1 sub-query.
If the query is complex or comparative (e.g., comparing emissions of different years, or analyzing multiple policies), generate up to 3 distinct search sub-queries focusing on key concepts to cover all aspects.

You must output a JSON object with the following keys:
- 'sub_queries': A list of strings, each being a search query for the vector database.
- 'reasoning': A brief explanation of your planning.

Output ONLY the raw JSON object. Do not wrap it in markdown blocks (no ```json).
"""

        user_content = f"User Question: {question}\n"
        if history_str:
            user_content += f"Chat History:\n{history_str}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            logger.info(f"Planner Agent generated plan: {result}")
            return result
        except Exception as e:
            logger.error(f"Planner Agent failed: {e}")
            # Fallback
            return {
                "sub_queries": [question],
                "reasoning": f"Fallback to raw question due to error: {e}"
            }


class RetrievalAgent:
    """
    Retrieval Agent executes planned sub-queries against the VectorStore,
    filters out duplicate passages, and ranks the merged results by relevance.
    """
    def __init__(self):
        pass

    def retrieve(self, vector_store, embedding_gen, sub_queries):
        logger.info(f"Retrieval Agent searching for sub-queries: {sub_queries}")
        all_chunks = []
        
        for query in sub_queries:
            try:
                # Generate query embedding
                embedding = embedding_gen.generate_single_embedding(query)
                # Search FAISS vector store
                chunks = vector_store.search(embedding, k=5)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"Retrieval Agent failed search for query '{query}': {e}")
                
        # Deduplicate chunks based on text content and rank by score descending
        seen_texts = set()
        deduplicated_chunks = []
        for chunk in all_chunks:
            norm_text = chunk['text'].strip()
            if norm_text not in seen_texts:
                seen_texts.add(norm_text)
                deduplicated_chunks.append(chunk)
                
        # Sort by score descending (higher Inner Product/cosine similarity score first)
        deduplicated_chunks.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        # Limit to top 8 most relevant chunks
        final_chunks = deduplicated_chunks[:8]
        logger.info(f"Retrieval Agent returned {len(final_chunks)} relevant chunks after deduplication and ranking.")
        return final_chunks


class ReasoningAgent:
    """
    Reasoning Agent drafts the response using ONLY the retrieved chunks.
    It takes feedback from the Verification Agent to refine drafts during retries.
    """
    def __init__(self, client):
        self.client = client
        self.model = Config.GROQ_CHAT_MODEL

    def generate_draft(self, question, retrieved_chunks, chat_history=None, correction_feedback=None):
        logger.info("Reasoning Agent drafting response...")
        
        # Format context
        context_str = ""
        for i, chunk in enumerate(retrieved_chunks):
            context_str += f"Context [{i}]: (Source: {chunk['source']})\n"
            context_str += f"Content: {chunk['text']}\n\n"
            
        # Compile chat history
        history_str = ""
        if chat_history:
            for msg in chat_history[-4:]:
                role = "User" if msg['role'] == 'user' else "Assistant"
                history_str += f"{role}: {msg['content']}\n"
                
        system_prompt = f"""You are the Reasoning Agent. Your task is to draft an answer to the User's question using ONLY the provided retrieved context chunks from a sustainability report.
You must adhere strictly to these constraints:
1. Your answer must be factual and fully grounded in the retrieved contexts below. Do not use outside knowledge.
2. If the context does not contain the answer, or if the user's question asks about something not mentioned, you must respond in JSON with the answer: "I could not find this information in the uploaded sustainability report." Set confidence to 'Low' and reasoning to 'Information not in context'.
3. Provide your response as a valid JSON object with the following keys:
   - 'answer': A detailed, professional markdown explanation that answers the user's question.
   - 'confidence': 'High' (if direct statistics or explicit statements are found), 'Medium' (if partial evidence is found), or 'Low' (if no direct answer is present).
   - 'reasoning': A brief one-sentence explanation of your answer and reasoning.
   - 'used_citations': A list of integers corresponding to the context indices (e.g., [0, 2]) that you actually used to write the answer.

Retrieved Context Chunks:
{context_str}
"""

        user_content = ""
        if history_str:
            user_content += f"Recent Chat History:\n{history_str}\n"
            
        if correction_feedback:
            user_content += f"CRITICAL - CORRECTION CRITIQUE FROM PREVIOUS ATTEMPT:\n{correction_feedback}\n\nPlease correct the draft response according to this critique. Make sure not to introduce any ungrounded assumptions or repeat the errors.\n\n"
            
        user_content += f"User Question: {question}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            logger.info("Reasoning Agent generated draft answer.")
            return result
        except Exception as e:
            logger.error(f"Reasoning Agent failed: {e}")
            return {
                "answer": "Error: Reasoning Agent failed to generate response.",
                "confidence": "Low",
                "reasoning": str(e),
                "used_citations": []
            }


class VerificationAgent:
    """
    Verification Agent validates the reasoning draft against the source chunks,
    detecting hallucinations, outside assumptions, or invalid citations.
    """
    def __init__(self, client):
        self.client = client
        self.model = Config.GROQ_CHAT_MODEL

    def verify(self, question, draft, retrieved_chunks):
        logger.info("Verification Agent fact-checking draft answer...")
        
        # Format context
        context_str = ""
        for i, chunk in enumerate(retrieved_chunks):
            context_str += f"Context [{i}]: (Source: {chunk['source']})\n"
            context_str += f"Content: {chunk['text']}\n\n"
            
        system_prompt = f"""You are the Verification Agent (Fact Checker). Your task is to review the draft answer and ensure it is 100% grounded in the provided context chunks.
Checks to perform:
1. Grounding check: Is every assertion/metric in the draft answer fully backed by the referenced context chunk?
2. Outside knowledge check: Did the Reasoning Agent introduce any assumptions or facts NOT mentioned in the contexts?
3. Citation validation: Are the 'used_citations' indices correct?
4. Constraint check: If the draft says "I could not find...", is it correct, or did it miss relevant information that actually exists in the contexts?

You must output a JSON object with the following keys:
- 'is_valid': boolean (true if draft is 100% grounded and correct, false if it contains hallucinations, ungrounded claims, incorrect citations, or is incomplete).
- 'critique': A detailed string explaining what is incorrect, hallucinated, or missing, referencing specific contexts. If valid, set to "".
- 'logs': A brief audit log of the checks you performed.

Retrieved Context Chunks:
{context_str}
"""

        user_content = f"User Question: {question}\n\nDraft Answer to Verify:\n{json.dumps(draft, indent=2)}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            logger.info(f"Verification Agent completed check: valid={result.get('is_valid')}, critique='{result.get('critique')}'")
            return result
        except Exception as e:
            logger.error(f"Verification Agent failed: {e}")
            # Safe default: fail validation and retry
            return {
                "is_valid": False,
                "critique": f"Verification failed due to internal error: {e}",
                "logs": "Failed to invoke verification LLM."
            }
