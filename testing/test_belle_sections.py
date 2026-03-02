"""Test Belle section detection on sample PDFs."""
import sys
import logging
import importlib
import types

sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO)

# Mock out heavy dependencies to allow importing Belle standalone
for mod_name in ['src.telemetry', 'src.observability', 'azure.ai', 'azure.ai.inference',
                 'azure.ai.inference.models', 'azure.ai.projects', 'azure.ai.projects.models']:
    m = types.ModuleType(mod_name)
    sys.modules[mod_name] = m

# Create mock telemetry
mock_tel = sys.modules['src.telemetry']
mock_tel.telemetry = type('T', (), {'track_agent_call': lambda *a, **k: None})()

# Mock observability
mock_obs = sys.modules['src.observability']
mock_obs.get_tracer = lambda name: type('Tracer', (), {'start_as_current_span': lambda self, *a, **k: __import__('contextlib').nullcontext()})()
mock_obs.should_capture_sensitive_data = lambda: False

# Mock inference models
mock_models = sys.modules['azure.ai.inference.models']
mock_models.SystemMessage = lambda **k: k
mock_models.UserMessage = lambda **k: k

from src.document_processor import DocumentProcessor

# Prevent src.agents.__init__ from loading all agents (which pulls in azure SDK)
# Pre-register a minimal src.agents module
agents_mod = types.ModuleType('src.agents')
agents_mod.__path__ = [str(__import__('pathlib').Path('src/agents').resolve())]
agents_mod.__package__ = 'src.agents'
sys.modules['src.agents'] = agents_mod

# Now import base_agent & belle only
from src.agents.base_agent import BaseAgent
agents_mod.BaseAgent = BaseAgent

from src.agents.belle_document_analyzer import BelleDocumentAnalyzer

PDFS = [
    "/Users/sleepy/Downloads/OneDrive_1_3-2-2026/Asekun, Korede.pdf",
    "/Users/sleepy/Downloads/OneDrive_1_3-2-2026/Augustus, Chloe'.pdf",
]


def test_pdf(pdf_path):
    print(f"\n{'='*70}")
    print(f"Testing: {pdf_path}")
    print(f"{'='*70}")

    # Extract text
    text = DocumentProcessor.extract_text_from_pdf(pdf_path)
    if not text:
        print("  ERROR: No text extracted!")
        return

    # Create a minimal Belle instance for section detection
    belle = BelleDocumentAnalyzer.__new__(BelleDocumentAnalyzer)
    belle.config = type('C', (), {'model_tier_lightweight': 'test', 'model_provider': 'test'})()
    belle.logger = logging.getLogger('belle')

    result = belle._detect_document_sections(text)

    print("\nSECTION MAP:")
    for page_num, info in sorted(result['section_map'].items()):
        scores = info.get('scores', {})
        ai_tag = ' [AI]' if info.get('ai_classified') else ''
        note = info.get('note', '')
        print(f"  Page {page_num:2d}: {info['type']:15s} T={scores.get('transcript',0):2d} R={scores.get('recommendation',0):2d} A={scores.get('application',0):2d}{ai_tag} {note}")

    t_pages = [p for p, i in result['section_map'].items() if i['type'] == 'transcript']
    r_pages = [p for p, i in result['section_map'].items() if i['type'] == 'recommendation']
    a_pages = [p for p, i in result['section_map'].items() if i['type'] == 'application']
    s_pages = [p for p, i in result['section_map'].items() if i['type'] == 'sparse']

    print(f"\nTranscript pages: {t_pages}")
    print(f"Recommendation pages: {r_pages}")
    print(f"Application pages: {a_pages}")
    print(f"Sparse pages: {s_pages}")
    print(f"\ntranscript_text: {len(result.get('transcript_text', ''))} chars")
    print(f"recommendation_text: {len(result.get('recommendation_text', ''))} chars")
    print(f"application_text: {len(result.get('application_text', ''))} chars")


for pdf in PDFS:
    try:
        test_pdf(pdf)
    except Exception as e:
        print(f"ERROR processing {pdf}: {e}")
        import traceback
        traceback.print_exc()
