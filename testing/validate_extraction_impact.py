"""Validate extraction improvements across all sample PDFs.

Compares before/after: how many pages would be OCR'd now vs before,
and how many sparse pages get recovered by adjacency fill.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.document_processor import _PAGINATION_FOOTER_RE, _IMAGE_PAGE_TEXT_THRESHOLD

import fitz

samples_dir = '/Users/sleepy/Downloads/OneDrive_1_3-2-2026'
pdfs = sorted([f for f in os.listdir(samples_dir) if f.endswith('.pdf')])

# Stats
total_pages = 0
pages_with_content = 0
sparse_before = 0  # Old logic: <100 chars → try OCR (if images or <20 chars)
sparse_after = 0   # New logic: also catches pagination footers
footer_pages_caught = 0  # Pages that are pagination-only + image → now OCR'd
adjacency_candidates = 0  # Sparse pages between same-type pages

for pdf_name in pdfs:
    path = os.path.join(samples_dir, pdf_name)
    doc = fitz.open(path)
    page_types = {}  # page_num -> 'content' or 'sparse'
    
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text().strip()
        images = page.get_images()
        char_count = len(text)
        page_num = page_idx + 1
        total_pages += 1
        
        is_footer = bool(_PAGINATION_FOOTER_RE.match(text)) if text else False
        effective_len = 0 if is_footer else char_count
        
        # Old logic
        old_would_ocr = (
            char_count < _IMAGE_PAGE_TEXT_THRESHOLD
            and (bool(images) or char_count < 20)
        )
        
        # New logic  
        new_would_ocr = (
            effective_len < _IMAGE_PAGE_TEXT_THRESHOLD
            and (bool(images) or effective_len < 20 or is_footer)
        )
        
        if char_count >= _IMAGE_PAGE_TEXT_THRESHOLD:
            pages_with_content += 1
            page_types[page_num] = 'content'
        else:
            page_types[page_num] = 'sparse'
            if old_would_ocr:
                sparse_before += 1
            if new_would_ocr:
                sparse_after += 1
            if is_footer and (bool(images) or char_count >= 20):
                # This is a footer page that old logic might miss
                # (old logic: char_count=29 >= 20 and no images → no OCR)
                if not old_would_ocr and new_would_ocr:
                    footer_pages_caught += 1
    
    # Check adjacency candidates
    sorted_pages = sorted(page_types.keys())
    for idx, pn in enumerate(sorted_pages):
        if page_types[pn] != 'sparse':
            continue
        prev_type = page_types.get(sorted_pages[idx - 1]) if idx > 0 else None
        next_type = page_types.get(sorted_pages[idx + 1]) if idx < len(sorted_pages) - 1 else None
        if prev_type == 'content' or next_type == 'content':
            adjacency_candidates += 1
    
    doc.close()

print(f"=== Extraction Improvement Impact ===")
print(f"Total PDFs analyzed: {len(pdfs)}")
print(f"Total pages: {total_pages}")
print(f"Pages with substantial content (>={_IMAGE_PAGE_TEXT_THRESHOLD} chars): {pages_with_content}")
print(f"Sparse pages (<{_IMAGE_PAGE_TEXT_THRESHOLD} chars): {total_pages - pages_with_content}")
print()
print(f"Pages OLD logic would OCR: {sparse_before}")
print(f"Pages NEW logic would OCR: {sparse_after}")
print(f"  Net new OCR pages (pagination footer fix): {footer_pages_caught}")
print(f"  Adjacency-fill candidates (sparse between content): {adjacency_candidates}")
print()
print(f"Improvement: {sparse_after - sparse_before} additional pages will now be OCR'd")
print(f"             {adjacency_candidates} sparse pages can be recovered via adjacency fill")
