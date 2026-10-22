import json
import logging
from openai import OpenAI
from config import Config
from embeddings import EmbeddingGenerator
from vector_store import VectorStore
from agents import PlannerAgent, RetrievalAgent, ReasoningAgent, VerificationAgent

logger = logging.getLogger(__name__)

class RAGPipeline:
    def __init__(self, report_id):
        self.report_id = report_id
        self.embedding_gen = EmbeddingGenerator()
        self.vector_store = VectorStore(report_id)
        
        # Initialize Groq Client if key is available
        self.api_key = Config.GROQ_API_KEY
        if self.api_key and self.api_key.strip() != "":
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=Config.GROQ_API_BASE
            )
        else:
            self.client = None

        # Instantiate agents
        if self.client:
            self.planner = PlannerAgent(self.client)
            self.retriever = RetrievalAgent()
            self.reasoner = ReasoningAgent(self.client)
            self.verifier = VerificationAgent(self.client)
        else:
            self.planner = None
            self.retriever = None
            self.reasoner = None
            self.verifier = None

    def query(self, question, chat_history=None):
        """
        Executes the Enterprise Agentic RAG pipeline:
        1. Planner Agent decomposes query based on chat history.
        2. Retrieval Agent fetches and deduplicates relevant context chunks.
        3. Multi-turn Generation and Verification loop (Self-Correction).
        """
        if not self.client:
            raise RuntimeError(
                "Groq API key is missing. Please set the GROQ_API_KEY in your .env file."
            )
            
        logger.info(f"Querying Agentic RAG pipeline for report {self.report_id}: '{question}'")
        
        # Step 1: Planning
        try:
            plan = self.planner.create_plan(question, chat_history)
            sub_queries = plan.get('sub_queries', [question])
            plan_reasoning = plan.get('reasoning', '')
        except Exception as e:
            logger.error(f"Planning failed, falling back to raw question: {e}")
            sub_queries = [question]
            plan_reasoning = "Planning failed."
            
        # Step 2: Retrieval
        retrieved_chunks = self.retriever.retrieve(self.vector_store, self.embedding_gen, sub_queries)
        if not retrieved_chunks:
            return {
                'answer': "I'm sorry, but I could not search the report. The vector index might be empty or corrupted.",
                'confidence': "Low",
                'reasoning': "No relevant text chunks were retrieved from the FAISS database.",
                'references': []
            }
            
        # Step 3: Synthesis & Verification Loop
        correction_feedback = None
        verification_history = []
        final_draft = None
        
        for attempt in range(3):
            logger.info(f"RAG Agentic loop: Attempt {attempt + 1} of 3")
            
            # Generate draft
            draft = self.reasoner.generate_draft(
                question=question,
                retrieved_chunks=retrieved_chunks,
                chat_history=chat_history,
                correction_feedback=correction_feedback
            )
            final_draft = draft
            
            # Verify draft
            verification = self.verifier.verify(
                question=question,
                draft=draft,
                retrieved_chunks=retrieved_chunks
            )
            
            is_valid = verification.get('is_valid', False)
            critique = verification.get('critique', '')
            audit_logs = verification.get('logs', '')
            
            verification_history.append({
                'attempt': attempt + 1,
                'valid': is_valid,
                'critique': critique,
                'logs': audit_logs
            })
            
            if is_valid:
                logger.info(f"RAG Agentic verification passed successfully on attempt {attempt + 1}.")
                break
            else:
                logger.warning(f"RAG Agentic verification failed on attempt {attempt + 1}. Feedback: {critique}")
                correction_feedback = critique
                
        # Resolve citations to original chunk dicts
        citations = []
        used_indices = final_draft.get('used_citations', [])
        
        # Fallback if LLM forgets to return citations list but answered
        if not used_indices and final_draft.get('confidence') != 'Low':
            used_indices = [0]
            
        for idx in used_indices:
            if 0 <= idx < len(retrieved_chunks):
                citations.append(retrieved_chunks[idx])
                
        # Compile agentic reasoning logs
        reasoning_trace = (
            f"**Planner sub-queries:** {', '.join(sub_queries)} ({plan_reasoning})\n\n"
            f"**Verification Audit Trace:**\n"
        )
        for history in verification_history:
            status = "PASSED" if history['valid'] else "FAILED"
            reasoning_trace += f"- **Attempt {history['attempt']} ({status})**: {history['logs']}\n"
            if not history['valid'] and history['critique']:
                reasoning_trace += f"  *Critique*: {history['critique']}\n"
                
        return {
            'answer': final_draft.get('answer', "I could not formulate an answer."),
            'confidence': final_draft.get('confidence', 'Low'),
            'reasoning': reasoning_trace,
            'references': citations,
            'retrieved_all': retrieved_chunks
        }

    def generate_esg_summary_and_profile(self, parsed_facts, parsed_chunks):
        """
        Generates an ESG Summary, Company Profile, and Predefined Prompts using the LLM.
        This runs right after uploading a report to create the dashboard and chatbot presets.
        """
        if not self.client:
            return "No API key configured to generate ESG summary.", "No API key configured.", []
            
        logger.info(f"Generating ESG summary, company profile, and prompts for report {self.report_id}")
        
        # Take a subset of facts and narrative texts (first 20 chunks + key concepts)
        sample_facts = parsed_facts[:30]
        sample_narratives = [c['text'] for c in parsed_chunks if c['source'] == 'Narrative Report Content'][:15]
        
        content_sample = "Key Facts extracted:\n"
        for f in sample_facts:
            unit_str = f" {f['unit']}" if f['unit'] else ""
            content_sample += f"- {f['concept_clean']}: {f['value']}{unit_str} ({f['period']})\n"
            
        if sample_narratives:
            content_sample += "\nNarrative Excerpts:\n"
            content_sample += "\n".join(sample_narratives)
            
        prompt = f"""Analyze the following data extracted from a Sustainability/ESG report.
Generate a professional company profile, a comprehensive ESG Summary, and 4 specific analysis questions/prompts.

Report Content Sample:
{content_sample}

Provide your response as a valid JSON object with the following keys:
- 'company_profile': A short company overview (1-2 paragraphs) detailing who the company is, their primary sector (if visible), and the scope/period of this sustainability report.
- 'esg_summary': A structured ESG analysis (in markdown format) with:
  1. **Environmental Commitments** (carbon emissions, energy, water, climate targets).
  2. **Social Indicators** (employee diversity, safety, community impact).
  3. **Governance Policies** (board composition, ethics, risk management).
- 'predefined_prompts': A list of exactly 4 specific, high-quality, and relevant analytical questions/prompts (each as a string) that are tailored specifically to this company's industry sector and report details.
  Follow these guidelines strictly:
  * If the company is in Pharmaceuticals: Focus prompts on hazardous chemical waste disposal, effluent treatment safeguards, water recycling ratios, product safety/quality compliance, or employee safety training hours.
  * If the company is in Banking & Financials: Focus prompts on digital banking footprints, paperless transactions, ESG lending/loan portfolios, or risk management committee policies.
  * If the company is in IT & Software: Focus prompts on data center energy efficiency, electricity consumption, e-waste recycling metrics, cybersecurity governance, data privacy, or women in leadership.
  * If the company is in Automobile/Manufacturing: Focus prompts on Scope 1 and Scope 2 manufacturing emissions, water recycling trends, worker safety, or supply chain ESG.
  * If the company is in Power & Energy: Focus prompts on renewable vs non-renewable generation capacity, carbon footprint mitigation targets, or green capital expenditures.
  Do NOT generate generic questions about general governance or international expansion. Make the prompts highly specific to the company's industry and report figures.

Output ONLY the raw JSON object. Do not wrap it in markdown block quotes (e.g. do not use ```json).
"""
        try:
            response = self.client.chat.completions.create(
                model=Config.GROQ_CHAT_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            res_json = json.loads(response.choices[0].message.content)
            return (
                res_json.get('esg_summary', ''),
                res_json.get('company_profile', ''),
                res_json.get('predefined_prompts', [])
            )
        except Exception as e:
            logger.error(f"Error generating ESG summary/profile/prompts: {e}")
            return (
                "Failed to generate ESG summary due to API error.",
                "Failed to extract company profile.",
                []
            )
