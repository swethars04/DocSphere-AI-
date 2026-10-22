import logging
from typing import List, Optional, Dict
from core.models import RetrievalResult
from indexing.hybrid_retriever import HybridRetriever

logger = logging.getLogger(__name__)

class RetrievalAgent:
    """
    Retrieval Agent coordinates hybrid vector and lexical retrieval across
    all decomposed sub-queries, filters by target company, and deduplicates passages.
    """

    def __init__(self, hybrid_retriever: HybridRetriever):
        self.retriever = hybrid_retriever

    def retrieve_and_deduplicate(
        self,
        sub_queries: List[str],
        company_names: Optional[List[str]] = None,
        top_k: int = 6
    ) -> List[RetrievalResult]:
        logger.info(f"Retrieval Agent searching for {len(sub_queries)} sub-queries with companies: {company_names}")

        merged_results: Dict[str, RetrievalResult] = {}

        for query in sub_queries:
            results = self.retriever.retrieve(
                query=query,
                top_k=top_k,
                company_names=company_names
            )
            for res in results:
                cid = res.chunk.chunk_id
                if cid not in merged_results:
                    merged_results[cid] = res
                else:
                    # Accumulate score across multiple sub-query matches
                    merged_results[cid].score += res.score

        # Sort combined results descending by score
        deduped = sorted(merged_results.values(), key=lambda x: x.score, reverse=True)
        final_chunks = deduped[:top_k]

        logger.info(f"Retrieval Agent consolidated {len(final_chunks)} unique passages.")
        return final_chunks

    @staticmethod
    def format_context_for_prompt(results: List[RetrievalResult]) -> str:
        """Formats retrieved chunks with strict provenance tags for LLM context."""
        if not results:
            return "No context found in the selected documents."

        formatted_blocks = []
        for idx, res in enumerate(results, 1):
            c = res.chunk
            header = f"[Source #{idx} | Company: {c.company_name} | Document: {c.document_name} | Location: {c.page_or_section}]"
            formatted_blocks.append(f"{header}\n{c.text}\n")

        return "\n---\n".join(formatted_blocks)
