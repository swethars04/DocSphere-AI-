import os
import re
import logging
from typing import List
from bs4 import BeautifulSoup
from core.models import ExtractionResult, RawExtractedSection
from core.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class TextHTMLParser(BaseParser):
    """Extracts clean text from HTML, HTM, TXT, and Markdown files."""

    def parse(self, file_path: str) -> ExtractionResult:
        filename = os.path.basename(file_path)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'txt'

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                raw_content = f.read()

            sections: List[RawExtractedSection] = []

            if ext in {'html', 'htm'}:
                soup = BeautifulSoup(raw_content, 'html.parser')
                
                # Remove boilerplate tags
                for bad_tag in soup(['script', 'style', 'nav', 'footer', 'noscript', 'header']):
                    bad_tag.decompose()

                # Extract content grouped by headings if available
                headings = soup.find_all(['h1', 'h2', 'h3', 'h4'])
                if headings:
                    for idx, h in enumerate(headings):
                        heading_title = h.get_text().strip()
                        content_nodes = []
                        curr = h.next_sibling
                        while curr and curr.name not in ['h1', 'h2', 'h3', 'h4']:
                            if hasattr(curr, 'get_text'):
                                t = curr.get_text().strip()
                                if t:
                                    content_nodes.append(t)
                            curr = curr.next_sibling
                            
                        section_text = "\n\n".join(content_nodes) if content_nodes else heading_title
                        cleaned = self.clean_text(section_text)
                        if cleaned:
                            sections.append(
                                RawExtractedSection(
                                    text=cleaned,
                                    page_or_section=f"Section: {heading_title[:60]}",
                                    metadata={"heading_index": idx + 1}
                                )
                            )

                # Fallback: if no headings found or sections empty, take body text
                if not sections:
                    body_text = soup.get_text(separator="\n\n")
                    cleaned = self.clean_text(body_text)
                    if cleaned:
                        sections.append(
                            RawExtractedSection(
                                text=cleaned,
                                page_or_section="Document Body",
                                metadata={}
                            )
                        )

            else:
                # Plain Text or Markdown file
                cleaned = self.clean_text(raw_content)
                # Split large text files into ~2000 character logical blocks
                lines = cleaned.split("\n\n")
                current_block: List[str] = []
                current_len = 0
                part_counter = 1

                for line in lines:
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    current_block.append(line_stripped)
                    current_len += len(line_stripped)

                    if current_len >= 2000:
                        block_text = "\n\n".join(current_block)
                        sections.append(
                            RawExtractedSection(
                                text=block_text,
                                page_or_section=f"Part {part_counter}",
                                metadata={"part": part_counter}
                            )
                        )
                        part_counter += 1
                        current_block = []
                        current_len = 0

                if current_block:
                    block_text = "\n\n".join(current_block)
                    sections.append(
                        RawExtractedSection(
                            text=block_text,
                            page_or_section=f"Part {part_counter}",
                            metadata={"part": part_counter}
                        )
                    )

            logger.info(f"Text/HTML parser extracted {len(sections)} sections from: {filename}")
            return ExtractionResult(
                filename=filename,
                file_type=ext,
                total_pages_or_sections=max(len(sections), 1),
                sections=sections,
                metadata={"file_extension": ext}
            )

        except Exception as e:
            logger.error(f"Error parsing text/html document {filename}: {e}")
            raise RuntimeError(f"Failed to parse text document {filename}: {str(e)}")
