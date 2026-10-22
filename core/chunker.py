import uuid
import re
from typing import List, Optional
from config import Config
from core.models import ExtractionResult, DocumentChunk

class SemanticChunker:
    """
    Context-aware semantic text chunker.
    Splits document sections on sentence/paragraph boundaries with overlap
    and stamps every chunk with company and citation location metadata.
    """

    def __init__(self, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None):
        self.chunk_size = chunk_size or Config.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or Config.CHUNK_OVERLAP

    def _split_into_sentences(self, text: str) -> List[str]:
        """Splits text cleanly using punctuation boundaries."""
        sentences = re.split(r'(?<=[.?!])\s+(?=[A-Z0-9])', text)
        return [s.strip() for s in sentences if s.strip()]

    def chunk_extraction_result(
        self,
        extraction: ExtractionResult,
        company_name: str,
        document_id: Optional[int] = None
    ) -> List[DocumentChunk]:
        """
        Transforms parsed structural sections into indexable, cited DocumentChunks.
        """
        chunks: List[DocumentChunk] = []
        global_chunk_idx = 0

        for section in extraction.sections:
            sec_text = section.text
            if not sec_text:
                continue

            # If section text is smaller than chunk_size, keep as a single chunk
            if len(sec_text) <= self.chunk_size:
                chunks.append(
                    DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        company_name=company_name,
                        document_name=extraction.filename,
                        file_type=extraction.file_type,
                        page_or_section=section.page_or_section,
                        text=sec_text,
                        chunk_index=global_chunk_idx,
                        extra_metadata=section.metadata
                    )
                )
                global_chunk_idx += 1
                continue

            # Otherwise, perform sliding-window sentence chunking
            sentences = self._split_into_sentences(sec_text)
            current_chunk_sentences: List[str] = []
            current_len = 0

            for sent in sentences:
                sent_len = len(sent)
                if current_len + sent_len > self.chunk_size and current_chunk_sentences:
                    chunk_body = " ".join(current_chunk_sentences)
                    chunks.append(
                        DocumentChunk(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            company_name=company_name,
                            document_name=extraction.filename,
                            file_type=extraction.file_type,
                            page_or_section=section.page_or_section,
                            text=chunk_body,
                            chunk_index=global_chunk_idx,
                            extra_metadata=section.metadata
                        )
                    )
                    global_chunk_idx += 1

                    # Retain overlap sentences from tail
                    overlap_sentences: List[str] = []
                    overlap_len = 0
                    for prev_sent in reversed(current_chunk_sentences):
                        if overlap_len + len(prev_sent) <= self.chunk_overlap:
                            overlap_sentences.insert(0, prev_sent)
                            overlap_len += len(prev_sent)
                        else:
                            break

                    current_chunk_sentences = overlap_sentences + [sent]
                    current_len = overlap_len + sent_len
                else:
                    current_chunk_sentences.append(sent)
                    current_len += sent_len

            if current_chunk_sentences:
                chunk_body = " ".join(current_chunk_sentences)
                chunks.append(
                    DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        company_name=company_name,
                        document_name=extraction.filename,
                        file_type=extraction.file_type,
                        page_or_section=section.page_or_section,
                        text=chunk_body,
                        chunk_index=global_chunk_idx,
                        extra_metadata=section.metadata
                    )
                )
                global_chunk_idx += 1

        return chunks
