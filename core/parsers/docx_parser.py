import os
import logging
from typing import List
from core.models import ExtractionResult, RawExtractedSection
from core.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class DocxParser(BaseParser):
    """Extracts text and tables from DOCX files, preserving section headings and tabular data."""

    def parse(self, file_path: str) -> ExtractionResult:
        filename = os.path.basename(file_path)
        try:
            import docx
        except ImportError:
            raise ImportError("python-docx is not installed. Please run `pip install python-docx`.")

        try:
            doc = docx.Document(file_path)
            sections: List[RawExtractedSection] = []
            
            current_heading = "Introduction / Overview"
            current_paragraphs: List[str] = []
            section_counter = 1

            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue

                # Check if paragraph is a heading style
                style_name = para.style.name.lower() if para.style else ""
                if "heading" in style_name or style_name.startswith("title"):
                    # Flush previous section
                    if current_paragraphs:
                        section_text = "\n\n".join(current_paragraphs)
                        cleaned = self.clean_text(section_text)
                        if cleaned:
                            sections.append(
                                RawExtractedSection(
                                    text=cleaned,
                                    page_or_section=f"Section: {current_heading}",
                                    metadata={"section_index": section_counter}
                                )
                            )
                            section_counter += 1
                        current_paragraphs = []
                    current_heading = text
                else:
                    current_paragraphs.append(text)

            # Flush remaining paragraphs
            if current_paragraphs:
                section_text = "\n\n".join(current_paragraphs)
                cleaned = self.clean_text(section_text)
                if cleaned:
                    sections.append(
                        RawExtractedSection(
                            text=cleaned,
                            page_or_section=f"Section: {current_heading}",
                            metadata={"section_index": section_counter}
                        )
                    )
                    section_counter += 1

            # Extract Tables as Markdown representations
            for t_idx, table in enumerate(doc.tables):
                table_rows = []
                for row in table.rows:
                    row_data = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
                    # Filter out empty duplicate merged cells if necessary
                    if any(row_data):
                        table_rows.append(" | ".join(row_data))
                
                if table_rows:
                    table_md = "\n".join([f"| {r} |" for r in table_rows])
                    sections.append(
                        RawExtractedSection(
                            text=f"Table {t_idx + 1} Data:\n{table_md}",
                            page_or_section=f"Table {t_idx + 1}",
                            metadata={"is_table": True, "table_index": t_idx + 1}
                        )
                    )

            logger.info(f"DOCX parser extracted {len(sections)} sections/tables from: {filename}")
            return ExtractionResult(
                filename=filename,
                file_type="docx",
                total_pages_or_sections=max(len(sections), 1),
                sections=sections,
                metadata={"total_sections": len(sections)}
            )

        except Exception as e:
            logger.error(f"DOCX parsing failed for {filename}: {e}")
            raise RuntimeError(f"Failed to parse DOCX {filename}: {str(e)}")
