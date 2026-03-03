"""Analyze sample PDFs to find extraction problem areas."""
import fitz
import os
import sys

samples_dir = '/Users/sleepy/Downloads/OneDrive_1_3-2-2026'
pdfs = sorted([f for f in os.listdir(samples_dir) if f.endswith('.pdf')])

zero_text_pages = []
sparse_text_pages = []

for pdf_name in pdfs:
    path = os.path.join(samples_dir, pdf_name)
    doc = fitz.open(path)
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text().strip()
        images = page.get_images()
        char_count = len(text)
        page_num = page_idx + 1

        if char_count == 0 and images:
            zero_text_pages.append((pdf_name, page_num, len(images)))
        elif char_count < 100 and images:
            sparse_text_pages.append((pdf_name, page_num, char_count, len(images), text[:80]))
        elif char_count < 50 and not images:
            sparse_text_pages.append((pdf_name, page_num, char_count, 0, text[:80]))
    doc.close()

print('=== ZERO TEXT + IMAGES (need OCR) ===')
for name, pn, imgs in zero_text_pages:
    print(f'  {name} page {pn}: {imgs} image(s)')
print(f'\nTotal zero-text image pages: {len(zero_text_pages)}')

print('\n=== SPARSE TEXT (<100 chars) ===')
for item in sparse_text_pages:
    name, pn, chars, imgs, preview = item
    print(f'  {name} page {pn}: {chars} chars, {imgs} imgs -- {repr(preview)}')
print(f'\nTotal sparse pages: {len(sparse_text_pages)}')

# Also check: how many PDFs have NO transcript detected
print('\n=== TRANSCRIPT PAGE DETECTION ===')
for pdf_name in pdfs:
    path = os.path.join(samples_dir, pdf_name)
    doc = fitz.open(path)
    has_transcript = False
    transcript_pages = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text().lower()
        if any(kw in text for kw in ['transcript', 'grade report', 'academic record', 'cumulative gpa', 'credit hours']):
            has_transcript = True
            transcript_pages.append(page_idx + 1)
    doc.close()
    status = f"pages {transcript_pages}" if has_transcript else "NO TRANSCRIPT FOUND"
    print(f'  {pdf_name}: {status}')
