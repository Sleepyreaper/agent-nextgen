#!/usr/bin/env python3
"""Batch transcript extraction diagnostic tool.

Processes a folder of student application PDFs through the full extraction
pipeline (DocumentProcessor → Belle section detection → Rapunzel grade parsing)
and produces a detailed diagnostic report showing exactly what was extracted
at each stage.

Usage:
    python scripts/diagnose_transcripts.py /path/to/pdf/folder [--output report.txt]

The report shows per-PDF:
  1. Page-by-page section classification (transcript/recommendation/application)
  2. Transcript text that Rapunzel receives (with char count)
  3. Rapunzel's extracted courses, GPA, rigor index
  4. The standardized transcript table
  5. Confidence and quality ratings

Review the report, note errors (e.g., "PDF 3: missed AP Chemistry, GPA should
be 3.9 not 2.8"), and feed corrections back to improve the prompts.

Requires:
  - Azure AI credentials (via Key Vault or .env/.env.local)
  - PyMuPDF (fitz) for PDF extraction
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.config import config
from src.document_processor import DocumentProcessor


def get_ai_client():
    """Create the Azure OpenAI client from config or DefaultAzureCredential.
    
    Attempts in order:
    1. Config-based Foundry client (if model_provider == 'foundry')
    2. Config-based AzureOpenAI with API key
    3. DefaultAzureCredential with known endpoint (for local dev via `az login`)
    """
    if config.model_provider and config.model_provider.lower() == "foundry":
        from azure.ai.inference import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential
        endpoint = config.foundry_endpoint
        key = config.foundry_api_key
        client = ChatCompletionsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        return client

    if getattr(config, 'azure_openai_api_key', None):
        from openai import AzureOpenAI
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=config.api_version,
            azure_endpoint=config.azure_openai_endpoint,
        )

    # Fallback: use DefaultAzureCredential (works with `az login`)
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    # Try configured endpoint first, then fall back to Foundry endpoint
    endpoint = getattr(config, 'azure_openai_endpoint', None)
    if not endpoint:
        endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT', 'https://nextgenagentfoundry.cognitiveservices.azure.com/')

    print(f"  Using DefaultAzureCredential with endpoint: {endpoint}")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version="2024-12-01-preview",
        azure_endpoint=endpoint,
    )


def make_ocr_callback(client):
    """Create an OCR callback using the vision model."""
    import base64 as _b64
    vision_model = getattr(config, 'foundry_vision_model_name', None) or 'gpt-4o'

    def _ocr(image_bytes: bytes, page_label: str) -> str:
        b64_image = _b64.b64encode(image_bytes).decode('utf-8')
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise document OCR system. Extract ALL text from "
                    "the image exactly as it appears. Preserve layout, tables, columns. "
                    "For tabular data, use aligned columns or ' | ' delimiters. "
                    "Do NOT summarize — reproduce text faithfully."
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract all text from this {page_label}:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}", "detail": "high"}}
                ]
            }
        ]
        try:
            # Support both AzureOpenAI (chat.completions.create) and Foundry (.complete)
            if hasattr(client, 'chat'):
                resp = client.chat.completions.create(messages=messages, model=vision_model, max_tokens=4000, temperature=0)
            else:
                resp = client.complete(messages=messages, model=vision_model, max_tokens=4000, temperature=0)
            return resp.choices[0].message.content or ""
        except Exception as e:
            print(f"  OCR error on {page_label}: {e}")
            return ""

    return _ocr


def run_belle_section_detection(text: str, client) -> dict:
    """Run Belle's section detection (keyword-based, no AI needed for most pages)."""
    from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
    # Create a minimal Belle instance with the AI client for fallback classification
    belle = BelleDocumentAnalyzer.__new__(BelleDocumentAnalyzer)
    belle.name = "Belle (Diagnostic)"
    belle.conversation_history = []
    belle.client = client
    belle.model = "gpt-4.1"
    # Run section detection
    result = belle._detect_document_sections(text)
    return result


async def run_rapunzel(client, transcript_text: str, student_name: str) -> dict:
    """Run Rapunzel grade extraction on transcript text."""
    from src.agents.rapunzel_grade_reader import RapunzelGradeReader
    rapunzel = RapunzelGradeReader(
        name="Rapunzel (Diagnostic)",
        client=client,
        model="gpt-4.1",
        db_connection=None
    )
    result = await rapunzel.parse_grades(
        transcript_text=transcript_text,
        student_name=student_name,
        school_context=None,
        application_id=None
    )
    return result


def format_section_map(section_map: dict) -> str:
    """Format the section map as a readable table."""
    if not section_map:
        return "  (no section map — document had no page markers)\n"
    lines = []
    for page_num in sorted(section_map.keys()):
        info = section_map[page_num]
        ptype = info.get('type', '?')
        scores = info.get('scores', {})
        notes = []
        if info.get('ai_classified'):
            notes.append('AI-classified')
        if info.get('adjacency_filled'):
            notes.append('adjacency-filled')
        if info.get('note'):
            notes.append(info['note'])
        t = scores.get('transcript', 0)
        r = scores.get('recommendation', 0)
        a = scores.get('application', 0)
        note_str = f" ({', '.join(notes)})" if notes else ""
        lines.append(f"  Page {page_num:2d}: {ptype:15s}  T={t:2d}  R={r:2d}  A={a:2d}{note_str}")
    return "\n".join(lines) + "\n"


def format_transcript_table(rows: list, headers: list) -> str:
    """Format transcript rows as a readable table."""
    if not rows or not headers:
        return "  (no standardized transcript table extracted)\n"
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    # Build table
    lines = []
    header_line = "  " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines.append(header_line)
    lines.append("  " + "-+-".join("-" * w for w in widths))
    for row in rows:
        cells = [str(row[i]).ljust(widths[i]) if i < len(row) else "".ljust(widths[i]) for i in range(len(headers))]
        lines.append("  " + " | ".join(cells))
    return "\n".join(lines) + "\n"


def process_pdf(pdf_path: str, client, use_ocr: bool = True) -> str:
    """Process a single PDF and return diagnostic output."""
    filename = os.path.basename(pdf_path)
    student_name = Path(pdf_path).stem.replace("_", " ").replace("-", " ").title()
    
    output = []
    output.append(f"\n{'='*80}")
    output.append(f"  FILE: {filename}")
    output.append(f"  Student (inferred): {student_name}")
    output.append(f"{'='*80}\n")
    
    # Stage 1: Text extraction
    t0 = time.time()
    ocr_cb = make_ocr_callback(client) if use_ocr else None
    
    try:
        ext = Path(pdf_path).suffix.lower()
        if ext == '.pdf':
            full_text = DocumentProcessor.extract_text_from_pdf(pdf_path, ocr_callback=ocr_cb)
        elif ext in ('.docx', '.doc'):
            full_text = DocumentProcessor.extract_text_from_docx(pdf_path)
        else:
            return f"  SKIPPED: unsupported file type '{ext}'\n"
    except Exception as e:
        return f"  ERROR extracting text: {e}\n"
    
    t1 = time.time()
    output.append(f"  STAGE 1 — Text Extraction ({t1-t0:.1f}s)")
    output.append(f"  Total text: {len(full_text)} chars")
    
    # Count pages
    import re
    page_markers = re.findall(r'--- PAGE (\d+) of (\d+) ---', full_text)
    if page_markers:
        output.append(f"  Pages: {len(page_markers)} (of {page_markers[0][1]} total)")
    else:
        output.append(f"  Pages: no page markers found")
    output.append("")
    
    # Stage 2: Belle section detection
    sections = run_belle_section_detection(full_text, client)
    t2 = time.time()
    
    output.append(f"  STAGE 2 — Belle Section Detection ({t2-t1:.1f}s)")
    output.append(format_section_map(sections.get('section_map', {})))
    
    transcript_text = sections.get('transcript_text') or ''
    recommendation_text = sections.get('recommendation_text') or ''
    application_text = sections.get('application_text') or ''
    
    output.append(f"  Section sizes:")
    output.append(f"    Transcript:      {len(transcript_text):6d} chars")
    output.append(f"    Recommendation:  {len(recommendation_text):6d} chars")
    output.append(f"    Application:     {len(application_text):6d} chars")
    
    # If no transcript detected, note the fallback
    if len(transcript_text.strip()) < 50:
        output.append(f"\n  ⚠️  TRANSCRIPT TEXT TOO SHORT ({len(transcript_text)} chars)")
        output.append(f"      Rapunzel would fall back to full document text ({len(full_text)} chars)")
        transcript_text = full_text
    
    output.append("")
    
    # Show first 500 chars of transcript text for review
    output.append(f"  TRANSCRIPT TEXT PREVIEW (first 500 chars):")
    output.append(f"  {'─'*60}")
    preview = transcript_text[:500].replace('\n', '\n  ')
    output.append(f"  {preview}")
    output.append(f"  {'─'*60}")
    output.append("")
    
    # Stage 3: Rapunzel grade extraction
    output.append(f"  STAGE 3 — Rapunzel Grade Extraction...")
    try:
        result = asyncio.run(run_rapunzel(client, transcript_text, student_name))
        t3 = time.time()
        output.append(f"  Completed in {t3-t2:.1f}s")
        output.append("")
        
        if result.get('status') == 'error':
            output.append(f"  ❌ ERROR: {result.get('error')}")
        else:
            # Key metrics
            output.append(f"  KEY METRICS:")
            output.append(f"    GPA:                {result.get('gpa', 'Not found')}")
            output.append(f"    Course Rigor Index:  {result.get('course_rigor_index', 'Not found')}")
            output.append(f"    Transcript Quality:  {result.get('transcript_quality', 'Not found')}")
            output.append(f"    Confidence:          {result.get('confidence_level', 'Not found')}")
            output.append(f"    Detected Format:     {result.get('detected_format', 'Not found')}")
            output.append(f"    Model Used:          {result.get('model_used', 'Not found')}")
            output.append("")
            
            # Notable patterns
            patterns = result.get('notable_patterns', [])
            if patterns:
                output.append(f"  NOTABLE PATTERNS:")
                for p in patterns:
                    output.append(f"    - {p}")
                output.append("")
            
            # Course levels
            levels = result.get('course_levels', {})
            if levels:
                output.append(f"  COURSE LEVELS:")
                for level, info in levels.items():
                    output.append(f"    {level}: {info}")
                output.append("")
            
            # Standardized transcript table
            headers = result.get('grade_table_headers', [])
            rows = result.get('grade_table_rows', [])
            output.append(f"  STANDARDIZED TRANSCRIPT TABLE ({len(rows)} courses):")
            output.append(format_transcript_table(rows, headers))
            
            # Rapunzel's Perspective (truncated)
            perspective = result.get('rapunzel_perspective', '')
            if perspective:
                output.append(f"  RAPUNZEL'S PERSPECTIVE (first 800 chars):")
                output.append(f"  {'─'*60}")
                output.append(f"  {perspective[:800].replace(chr(10), chr(10) + '  ')}")
                output.append(f"  {'─'*60}")
            
            # Summary
            summary = result.get('summary', '')
            if summary:
                output.append(f"\n  EXECUTIVE SUMMARY:")
                output.append(f"  {summary[:500]}")
            
    except Exception as e:
        output.append(f"  ❌ Rapunzel ERROR: {e}")
        import traceback
        output.append(f"  {traceback.format_exc()}")
    
    output.append("")
    return "\n".join(output)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch transcript extraction diagnostics")
    parser.add_argument("folder", help="Path to folder containing PDF files")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)", default=None)
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR (faster but misses scanned pages)")
    parser.add_argument("--limit", "-n", type=int, default=0, help="Max number of PDFs to process (0=all)")
    parser.add_argument("--skip", "-s", type=int, default=0, help="Number of PDFs to skip from the start")
    args = parser.parse_args()
    
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory")
        sys.exit(1)
    
    # Find PDFs
    pdfs = sorted([
        str(f) for f in folder.iterdir()
        if f.suffix.lower() in ('.pdf', '.docx')
    ])
    
    if not pdfs:
        print(f"No PDF/DOCX files found in '{folder}'")
        sys.exit(1)
    
    if args.skip > 0:
        pdfs = pdfs[args.skip:]
    if args.limit > 0:
        pdfs = pdfs[:args.limit]
    
    print(f"Found {len(pdfs)} files to process (skip={args.skip})")
    print(f"OCR: {'enabled' if not args.no_ocr else 'disabled'}")
    print(f"Model: {config.model_tier_premium or config.foundry_model_name or 'default'}")
    print()
    
    # Create AI client
    try:
        client = get_ai_client()
        print("AI client initialized successfully")
    except Exception as e:
        print(f"Error creating AI client: {e}")
        print("Check your .env.local or Azure Key Vault configuration")
        sys.exit(1)
    
    # Process each PDF
    all_output = []
    all_output.append(f"TRANSCRIPT EXTRACTION DIAGNOSTIC REPORT")
    all_output.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    all_output.append(f"Files: {len(pdfs)}")
    all_output.append(f"OCR: {'enabled' if not args.no_ocr else 'disabled'}")
    all_output.append(f"Model: {config.model_tier_premium or 'default'}")
    all_output.append(f"{'='*80}\n")
    
    for i, pdf_path in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] Processing {os.path.basename(pdf_path)}...")
        result = process_pdf(pdf_path, client, use_ocr=not args.no_ocr)
        all_output.append(result)
        print(f"  Done.")
    
    # Summary
    all_output.append(f"\n{'='*80}")
    all_output.append(f"  END OF REPORT — {len(pdfs)} files processed")
    all_output.append(f"{'='*80}\n")
    
    report = "\n".join(all_output)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"\nReport written to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
