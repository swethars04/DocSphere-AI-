import os
import re
import logging
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from core.models import ExtractionResult, RawExtractedSection
from core.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class XBRLParser(BaseParser):
    """
    Parses XBRL and Inline XBRL (iXBRL) documents.
    Resolves contexts (instant / duration periods), entity identifiers, numeric facts,
    and narrative disclosures, mapping them into structured sections for RAG retrieval.
    """

    def parse(self, file_path: str) -> ExtractionResult:
        filename = os.path.basename(file_path)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            is_html = bool(re.search(r'<!DOCTYPE html|<html', content, re.IGNORECASE))
            parser_type = 'lxml' if is_html else 'xml'
            soup = BeautifulSoup(content, parser_type)

            # 1. Parse Contexts
            contexts: Dict[str, Dict[str, str]] = {}
            context_tags = soup.find_all(lambda t: t.name and t.name.split(':')[-1] == 'context')
            for tag in context_tags:
                ctx_id = tag.get('id')
                if not ctx_id:
                    continue
                period_str = "Unknown Period"
                period_tag = tag.find(lambda t: t.name and t.name.split(':')[-1] == 'period')
                if period_tag:
                    instant = period_tag.find(lambda t: t.name and t.name.split(':')[-1] == 'instant')
                    if instant:
                        period_str = f"As of {instant.get_text().strip()}"
                    else:
                        start_date = period_tag.find(lambda t: t.name and t.name.split(':')[-1] == 'startdate')
                        end_date = period_tag.find(lambda t: t.name and t.name.split(':')[-1] == 'enddate')
                        if start_date and end_date:
                            period_str = f"Period: {start_date.get_text().strip()} to {end_date.get_text().strip()}"

                contexts[ctx_id] = {"period": period_str}

            # 2. Extract Facts (Numeric & Non-Numeric)
            facts_by_context: Dict[str, List[str]] = {}
            for tag in soup.find_all(True):
                # Filter out standard metadata structural wrappers
                tag_name_clean = tag.name.split(':')[-1].lower() if tag.name else ""
                if tag_name_clean in {'xbrl', 'schema', 'context', 'unit', 'header', 'html', 'body', 'head'}:
                    continue

                ctx_ref = tag.get('contextref') or tag.get('contextRef')
                if not ctx_ref:
                    continue

                val = tag.get_text(separator=" ", strip=True)
                if not val or len(val) > 10000:  # Skip empty or massive raw blobs
                    continue

                tag_display = tag.name.split(':')[-1]
                period = contexts.get(ctx_ref, {}).get("period", "General Context")
                
                fact_statement = f"{tag_display}: {val}"
                if period not in facts_by_context:
                    facts_by_context[period] = []
                facts_by_context[period].append(fact_statement)

            sections: List[RawExtractedSection] = []
            for period, fact_list in facts_by_context.items():
                # Group facts in batches of 25 facts per section
                batch_size = 25
                for i in range(0, len(fact_list), batch_size):
                    batch = fact_list[i:i + batch_size]
                    joined_facts = "\n".join(batch)
                    cleaned = self.clean_text(joined_facts)
                    if cleaned:
                        sections.append(
                            RawExtractedSection(
                                text=cleaned,
                                page_or_section=f"XBRL {period} (Part {i // batch_size + 1})",
                                metadata={"period": period}
                            )
                        )

            # If no structured facts found, extract readable body paragraphs
            if not sections:
                paragraphs = [p.get_text().strip() for p in soup.find_all(['p', 'div']) if len(p.get_text().strip()) > 40]
                if paragraphs:
                    cleaned_body = self.clean_text("\n\n".join(paragraphs[:100]))
                    sections.append(
                        RawExtractedSection(
                            text=cleaned_body,
                            page_or_section="Document Body Content",
                            metadata={}
                        )
                    )

            logger.info(f"XBRL parser extracted {len(sections)} contextual sections from: {filename}")
            return ExtractionResult(
                filename=filename,
                file_type="xbrl",
                total_pages_or_sections=max(len(sections), 1),
                sections=sections,
                metadata={"contexts_count": len(contexts)}
            )

        except Exception as e:
            logger.error(f"XBRL parsing error for {filename}: {e}")
            raise RuntimeError(f"Failed to parse XBRL document {filename}: {str(e)}")
