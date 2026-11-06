from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class RawExtractedSection(BaseModel):
    """Represents an extracted structural unit (e.g., page, heading section, or XML context block)."""
    text: str
    page_or_section: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ExtractionResult(BaseModel):
    """Represents the raw parsed output from any format parser."""
    filename: str
    file_type: str
    total_pages_or_sections: int
    sections: List[RawExtractedSection]
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentChunk(BaseModel):
    """Represents an indexed chunk bound with company, document, and location metadata for citations."""
    chunk_id: str
    company_name: str
    document_name: str
    file_type: str
    page_or_section: str
    text: str
    chunk_index: int
    document_id: Optional[int] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

class RetrievalResult(BaseModel):
    """Represents a retrieved chunk with score and ranking provenance."""
    chunk: DocumentChunk
    score: float
    retrieval_source: str  # 'vector', 'bm25', or 'hybrid'

def is_information_unavailable(text: str) -> bool:
    """Checks if an answer states that requested info is not available or absent from documents."""
    if not text:
        return True
    
    clean_text = text.strip()
    text_lower = clean_text.lower()
    
    # Check if the opening sentence specifically declares info is unavailable
    first_150 = text_lower[:150]
    starts_unavailable = any(
        first_150.startswith(prefix) for prefix in [
            "information not available",
            "the provided documents do not contain",
            "the documents do not contain",
            "these documents do not contain",
            "no information provided",
            "no relevant information",
            "i could not find any information",
            "the requested information is not available",
            "unable to find information",
            "sorry, the provided documents"
        ]
    )
    
    # Substantive content check:
    # If it has structured answers (bullet points, numbered lists, markdown headers)
    # and is of substantial length (>200 chars), it is an informative answer, NOT an unavailable response.
    has_structure = (
        "\n* " in clean_text or 
        "\n- " in clean_text or 
        "\n1." in clean_text or 
        "\n2." in clean_text or 
        "### " in clean_text or 
        "## " in clean_text
    )
    
    if len(clean_text) > 200 and has_structure and not starts_unavailable:
        return False
        
    # If the text explicitly starts with positive grounding ("based on the provided/retrieved documents...")
    if (first_150.startswith("based on the provided") or first_150.startswith("based on the retrieved")) and len(clean_text) > 150:
        if "information not available" not in first_150 and "does not contain" not in first_150 and "no information" not in first_150:
            return False

    unavailable_markers = [
        "information not available",
        "not available in the selected documents",
        "not available in the provided",
        "not found in the provided",
        "not found in the selected",
        "no information provided",
        "no relevant information",
        "cannot be found in the provided",
        "cannot be found in the selected",
        "does not contain information",
        "do not contain information",
        "documents do not contain",
        "does not contain any information",
        "unable to find information",
        "could not find any information",
        "no data available"
    ]
    
    # Short responses (< 350 chars) without structure that contain unavailability markers
    if len(clean_text) < 350 and any(marker in text_lower for marker in unavailable_markers):
        return True

    # If it explicitly started with an unavailability declaration and doesn't have structured answers
    if starts_unavailable and not has_structure:
        return True

    return False


def clean_latex_math(content: str) -> str:
    """
    Cleans raw LaTeX math notation (e.g. $$6 \\text{ days} - 2 = \\mathbf{4}$$ or $...$)
    into clean, natural, readable plain text / Markdown.
    Prevents unparsed LaTeX code from rendering as visual glitches or syntax errors in the chat UI.
    """
    if not content:
        return content

    import re

    def replace_math(expr: str) -> str:
        simplified = expr
        # Run multiple passes to clean nested \\mathbf{\\text{...}}
        for _ in range(3):
            simplified = re.sub(r'\\text\{([^{}]+)\}', r'\1', simplified)
            simplified = re.sub(r'\\mathbf\{([^{}]+)\}', r'\1', simplified)
            simplified = re.sub(r'\\textbf\{([^{}]+)\}', r'\1', simplified)
        simplified = re.sub(r'\\times', '×', simplified)
        simplified = re.sub(r'\\div', '÷', simplified)
        simplified = re.sub(r'\\pm', '±', simplified)
        simplified = re.sub(r'\\le', '≤', simplified)
        simplified = re.sub(r'\\ge', '≥', simplified)
        simplified = re.sub(r'\\neq', '≠', simplified)
        simplified = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1 / \2)', simplified)
        simplified = re.sub(r'\s+', ' ', simplified).strip()
        return f"**{simplified}**"

    # Replace block $$ ... $$
    cleaned = re.sub(r'\$\$(.*?)\$\$', lambda m: replace_math(m.group(1)), content, flags=re.DOTALL)
    # Replace inline $ ... $ (ignoring currency like $100)
    cleaned = re.sub(
        r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$',
        lambda m: replace_math(m.group(1)) if any(sym in m.group(1) for sym in ['\\', '=', '+', '-', '×', '÷', '/']) else m.group(0),
        cleaned
    )
    return cleaned

