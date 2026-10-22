import re
from abc import ABC, abstractmethod
from core.models import ExtractionResult

class BaseParser(ABC):
    """Abstract Base Class for all multi-format document parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> ExtractionResult:
        """
        Parses a target document and extracts its structural sections with location tracking.
        
        Args:
            file_path: Absolute or relative path to the document file.
            
        Returns:
            ExtractionResult containing list of RawExtractedSection with page/section anchors.
        """
        pass

    @staticmethod
    def clean_text(text: str) -> str:
        """Sanitizes raw text: normalizes whitespace, removes control chars and empty lines."""
        if not text:
            return ""
        # Replace non-breaking spaces and tabs
        text = text.replace('\xa0', ' ').replace('\t', ' ')
        # Collapse multiple spaces
        text = re.sub(r'[ ]{2,}', ' ', text)
        # Collapse multiple newlines into a maximum of two
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
