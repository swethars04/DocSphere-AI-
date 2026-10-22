import os
import re
import logging
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Silence XML parsed as HTML warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

def validate_xbrl_file(file_path):
    """
    Validates if a file is an XBRL or Inline XBRL report.
    Checks for the existence of standard XBRL/iXBRL tags or namespaces.
    """
    if not os.path.exists(file_path):
        return False, "File does not exist."
        
    try:
        # Read the first 5000 characters to check namespaces/tags
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.read(10000)
            
        # Common indicators of XBRL/iXBRL
        indicators = [
            r'xmlns:xbrli\s*=',
            r'xmlns:ix\s*=',
            r'<xbrl\b',
            r'<ix:nonNumeric\b',
            r'<ix:nonFraction\b',
            r'<ix:numeric\b',
            r'http://www.xbrl.org/',
            r'http://www.esef.eu/'
        ]
        
        for indicator in indicators:
            if re.search(indicator, header, re.IGNORECASE):
                return True, "Valid XBRL/iXBRL file detected."
                
        # Also allow standard XML or HTML structure if it contains financial elements
        if re.search(r'<\?xml\b', header, re.IGNORECASE) or re.search(r'<!DOCTYPE html\b', header, re.IGNORECASE) or re.search(r'<html\b', header, re.IGNORECASE):
             return True, "Valid XML/HTML document (potential XBRL/iXBRL)."
             
        return False, "File does not appear to be a valid XBRL or Inline XBRL document. Missing standard namespaces/tags."
    except Exception as e:
        logger.error(f"Error validating file: {e}")
        return False, f"Error validating file: {str(e)}"


def parse_xbrl_document(file_path):
    """
    Parses an XBRL/iXBRL file and returns:
    1. metadata: A dict of company, period, and document properties.
    2. facts: A list of dicts representing individual tags and their contextualized values.
    3. chunks: A list of strings (structured sentences and text paragraphs) for indexing.
    """
    logger.info(f"Parsing XBRL/iXBRL file: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Determine whether to parse as XML or HTML
    is_html = bool(re.search(r'<!DOCTYPE html|<html', content, re.IGNORECASE))
    parser_type = 'lxml' if is_html else 'xml'
    
    soup = BeautifulSoup(content, parser_type)
    
    # 1. Parse Contexts
    contexts = {}
    context_tags = soup.find_all(lambda tag: tag.name.split(':')[-1] == 'context')
    for tag in context_tags:
        ctx_id = tag.get('id')
        if not ctx_id:
            continue
            
        # Extract Period
        period_tag = tag.find(lambda t: t.name.split(':')[-1] == 'period')
        period_str = "Unknown Period"
        if period_tag:
            # Check for instant date
            instant = period_tag.find(lambda t: t.name.split(':')[-1] == 'instant')
            if instant:
                period_str = f"As of {instant.get_text().strip()}"
            else:
                start_date = period_tag.find(lambda t: t.name.split(':')[-1] == 'startdate')
                end_date = period_tag.find(lambda t: t.name.split(':')[-1] == 'enddate')
                if start_date and end_date:
                    period_str = f"Period from {start_date.get_text().strip()} to {end_date.get_text().strip()}"
                    
        # Extract Entity Identifier
        entity_tag = tag.find(lambda t: t.name.split(':')[-1] == 'entity')
        entity_str = ""
        if entity_tag:
            identifier = entity_tag.find(lambda t: t.name.split(':')[-1] == 'identifier')
            if identifier:
                entity_str = identifier.get_text().strip()
                
        contexts[ctx_id] = {
            'period': period_str,
            'entity': entity_str
        }
        
    # 2. Parse Units
    units = {}
    unit_tags = soup.find_all(lambda tag: tag.name.split(':')[-1] == 'unit')
    for tag in unit_tags:
        unit_id = tag.get('id')
        if not unit_id:
            continue
        measure = tag.find(lambda t: t.name.split(':')[-1] == 'measure')
        units[unit_id] = measure.get_text().strip() if measure else "unit"

    # 3. Parse Facts (all elements with contextRef)
    facts = []
    fact_tags = soup.find_all(lambda tag: tag.has_attr('contextRef') or tag.has_attr('contextref'))
    
    # We will also try to extract key metadata while parsing facts
    company_name = None
    reporting_period = None
    document_type = "Sustainability Report"
    
    for tag in fact_tags:
        # Determine the concept name (tag name or 'name' attribute for ix: elements)
        full_tag_name = tag.name
        concept = full_tag_name
        if full_tag_name.startswith('ix:') and tag.has_attr('name'):
            concept = tag.get('name')
            
        context_ref = tag.get('contextRef') or tag.get('contextref')
        unit_ref = tag.get('unitRef') or tag.get('unitref')
        decimals = tag.get('decimals')
        value = tag.get_text().strip()
        
        # Skip empty facts
        if not value:
            continue
            
        # Look up context and unit
        ctx = contexts.get(context_ref, {'period': 'Unknown Period', 'entity': ''})
        unit = units.get(unit_ref, '')
        
        # Clean concept name for readability
        concept_clean = concept.split(':')[-1] if ':' in concept else concept
        
        # Capture metadata if matching standard DEI (Document and Entity Information) concepts
        concept_lower = concept.lower()
        if 'entityregistrantname' in concept_lower or 'companyname' in concept_lower:
            company_name = value
        elif 'documentfiscalyear' in concept_lower or 'reportperiod' in concept_lower:
            reporting_period = value
        elif 'documenttype' in concept_lower:
            document_type = value
            
        fact_dict = {
            'concept': concept,
            'concept_clean': concept_clean,
            'value': value,
            'context_ref': context_ref,
            'period': ctx['period'],
            'entity': ctx['entity'],
            'unit_ref': unit_ref,
            'unit': unit,
            'decimals': decimals
        }
        facts.append(fact_dict)
        
    # 4. Generate structured text sentences from facts for the index
    structured_chunks = []
    for f in facts:
        unit_str = f" {f['unit']}" if f['unit'] else ""
        period_str = f"[{f['period']}]"
        # Create a self-contained descriptive fact sentence
        fact_sentence = f"{period_str} Fact: The value for '{f['concept_clean']}' ({f['concept']}) is '{f['value']}'{unit_str}."
        structured_chunks.append({
            'text': fact_sentence,
            'source': f"XBRL Fact (Concept: {f['concept']}, Context: {f['context_ref']})"
        })
        
    # 5. Narrative Text Extraction (Paragraphs/Lists for Inline XBRL/HTML)
    narrative_chunks = []
    if is_html:
        # Extract textual elements to catch descriptive sections like governance, policies, etc.
        text_tags = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'span'])
        current_chunk = []
        current_len = 0
        
        for t in text_tags:
            text = t.get_text().strip()
            # Clean spaces
            text = re.sub(r'\s+', ' ', text)
            
            # Skip very short sentences or elements that are just numbers (which are likely facts we already parsed)
            if len(text) < 30 or text.replace('.', '', 1).isdigit():
                continue
                
            # Keep chunks structured around 600 characters
            if current_len + len(text) > 600:
                chunk_text = " ".join(current_chunk)
                narrative_chunks.append({
                    'text': chunk_text,
                    'source': "Narrative Report Content"
                })
                # Overlap: keep the last 1-2 elements
                if len(current_chunk) > 1:
                    current_chunk = current_chunk[-1:]
                    current_len = sum(len(x) for x in current_chunk)
                else:
                    current_chunk = []
                    current_len = 0
                    
            current_chunk.append(text)
            current_len += len(text)
            
        if current_chunk:
            narrative_chunks.append({
                'text': " ".join(current_chunk),
                'source': "Narrative Report Content"
            })
            
    # Combine chunks
    all_chunks = structured_chunks + narrative_chunks
    
    # Standard Metadata Fallbacks
    if not company_name:
        # Try to guess from facts
        for f in facts:
            if 'registrant' in f['concept_clean'].lower() or 'company' in f['concept_clean'].lower():
                company_name = f['value']
                break
        if not company_name:
            company_name = "Unknown Company"
            
    if not reporting_period:
        # Get most common year or period from contexts
        years = []
        for ctx in contexts.values():
            m = re.search(r'\b(20\d{2})\b', ctx['period'])
            if m:
                years.append(m.group(1))
        if years:
            reporting_period = max(set(years), key=years.count)
        else:
            reporting_period = "Unknown Period"
            
    metadata = {
        'company_name': company_name,
        'reporting_period': reporting_period,
        'document_type': document_type,
        'fact_count': len(facts),
        'chunk_count': len(all_chunks)
    }
    
    return metadata, facts, all_chunks
