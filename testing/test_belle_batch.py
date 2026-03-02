#!/usr/bin/env python3
"""
Batch test Belle section detection across multiple student PDFs.
Runs without Azure dependencies by mocking them.
"""
import sys, os, re, types, importlib, contextlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── Mock external dependencies (same approach as test_belle_sections.py) ──
for mod_name in [
    'src.telemetry', 'src.observability',
    'azure', 'azure.ai', 'azure.ai.projects', 'azure.ai.projects.models',
    'azure.ai.inference', 'azure.ai.inference.models',
    'azure.identity', 'azure.keyvault', 'azure.keyvault.secrets',
    'opentelemetry', 'opentelemetry.trace',
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Create mock telemetry with .telemetry attribute
mock_tel = sys.modules['src.telemetry']
mock_tel.telemetry = type('T', (), {'track_agent_call': lambda *a, **kw: None})()
mock_tel.with_agent_span = lambda name: (lambda f: f)

# Mock observability
mock_obs = sys.modules['src.observability']
mock_obs.get_tracer = lambda name: type('Tracer', (), {
    'start_as_current_span': lambda self, *a, **kw: contextlib.nullcontext()
})()
mock_obs.should_capture_sensitive_data = lambda: False
mock_obs.track_agent_call = lambda **kw: (lambda f: f)

# Mock inference models
mock_models = sys.modules['azure.ai.inference.models']
mock_models.SystemMessage = lambda **k: k
mock_models.UserMessage = lambda **k: k

# Stub opentelemetry trace
ot = sys.modules['opentelemetry.trace']
ot.get_tracer = lambda *a, **kw: None
ot.SpanKind = type('SpanKind', (), {'CLIENT': 0, 'SERVER': 1, 'INTERNAL': 2})()
ot.StatusCode = type('StatusCode', (), {'OK': 0, 'ERROR': 1})()

# Register stub 'src.agents' so __init__.py doesn't pull in every agent
agents_mod = types.ModuleType('src.agents')
agents_mod.__path__ = [str(importlib.import_module('pathlib').Path('src/agents').resolve())]
agents_mod.__package__ = 'src.agents'
sys.modules['src.agents'] = agents_mod

# Import base agent first
from src.agents.base_agent import BaseAgent
agents_mod.BaseAgent = BaseAgent

from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.document_processor import DocumentProcessor

PDF_DIR = "/Users/sleepy/Downloads/OneDrive_1_3-2-2026/"

# Expected structure: most PDFs follow the pattern:
# TOC → application pages → transcript → recommendation letters → sparse footers
# We check that:
# 1. At least one page is classified as transcript
# 2. At least one page is classified as recommendation
# 3. At least one page is classified as application

def test_pdf(filepath):
    """Test a single PDF, return summary dict."""
    name = os.path.basename(filepath)
    pages = DocumentProcessor.extract_text_from_pdf(filepath)
    if not pages:
        return {'name': name, 'status': 'EMPTY', 'pages': 0, 'sections': {}}
    
    belle = BelleDocumentAnalyzer.__new__(BelleDocumentAnalyzer)
    result = belle._detect_document_sections(pages)
    sections = result.get('section_map', {})
    
    counts = {'application': 0, 'transcript': 0, 'recommendation': 0, 'sparse': 0}
    for page_num, info in sections.items():
        section = info.get('type', 'unknown') if isinstance(info, dict) else str(info)
        if section in counts:
            counts[section] += 1
    
    # Determine status
    issues = []
    if counts['transcript'] == 0:
        issues.append('NO_TRANSCRIPT')
    if counts['recommendation'] == 0:
        issues.append('NO_RECOMMENDATION')
    if counts['application'] == 0:
        issues.append('NO_APPLICATION')
    if counts['transcript'] > 3:
        issues.append(f'MANY_TRANSCRIPTS({counts["transcript"]})')
    if counts['recommendation'] > 4:
        issues.append(f'MANY_RECOMMENDATIONS({counts["recommendation"]})')
    
    status = 'OK' if not issues else ', '.join(issues)
    return {
        'name': name,
        'status': status,
        'pages': len(sections),  # Number of classified pages
        'sections': counts,
        'details': sections  # This is result['section_map']
    }

def main():
    import glob, random, logging
    logging.basicConfig(level=logging.WARNING)  # Suppress INFO for batch mode
    
    pdfs = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf")))
    
    # Sample: first 10, last 5, and 5 random from the middle
    sample_indices = list(range(min(10, len(pdfs))))
    sample_indices += list(range(max(0, len(pdfs)-5), len(pdfs)))
    random.seed(42)
    middle = list(range(10, max(10, len(pdfs)-5)))
    if middle:
        sample_indices += random.sample(middle, min(5, len(middle)))
    sample_indices = sorted(set(sample_indices))
    
    sample_pdfs = [pdfs[i] for i in sample_indices if i < len(pdfs)]
    
    print(f"Testing {len(sample_pdfs)} PDFs out of {len(pdfs)} total\n")
    print(f"{'Name':<45} {'Pages':>5}  {'App':>3} {'Trn':>3} {'Rec':>3} {'Spr':>3}  Status")
    print("-" * 100)
    
    issues_found = []
    for pdf_path in sample_pdfs:
        result = test_pdf(pdf_path)
        name_short = result['name'][:44]
        s = result['sections']
        status_marker = '✅' if result['status'] == 'OK' else '⚠️'
        print(f"{name_short:<45} {result['pages']:>5}  {s.get('application',0):>3} {s.get('transcript',0):>3} {s.get('recommendation',0):>3} {s.get('sparse',0):>3}  {status_marker} {result['status']}")
        
        if result['status'] != 'OK':
            issues_found.append(result)
    
    print(f"\n{'='*100}")
    print(f"Summary: {len(sample_pdfs) - len(issues_found)}/{len(sample_pdfs)} PDFs classified with expected sections")
    
    if issues_found:
        print(f"\n⚠️ PDFs with potential issues:")
        for r in issues_found:
            print(f"\n  {r['name']}:")
            for page_num, info in sorted(r['details'].items()):
                if isinstance(info, dict):
                    section = info.get('type', '?')
                    scores = info.get('scores', {})
                    note = info.get('note', '')
                    t = scores.get('transcript', 0)
                    rec = scores.get('recommendation', 0)
                    a = scores.get('application', 0)
                else:
                    section = str(info)
                    t = rec = a = 0
                    note = ''
                print(f"    Page {page_num:>2}: {section:<15} T={t:>2} R={rec:>2} A={a:>2}  {note}")

if __name__ == '__main__':
    main()
