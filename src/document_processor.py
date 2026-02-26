"""Document processing utilities for extracting text from various file formats."""

import base64
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from docx import Document

logger = logging.getLogger(__name__)

# Minimum characters on a page before it's considered "image-based"
_IMAGE_PAGE_TEXT_THRESHOLD = 100


class DocumentProcessor:
    """Process and extract text from uploaded documents."""
    
    @staticmethod
    def extract_text_from_pdf(
        file_path: str,
        ocr_callback: Optional[Callable[[bytes, str], str]] = None,
    ) -> str:
        """Extract text from PDF file with page markers.
        
        Uses PyMuPDF (fitz) for text extraction.  When a page yields fewer
        than _IMAGE_PAGE_TEXT_THRESHOLD characters **and** contains an
        embedded image, the page is rendered to a PNG and passed to
        *ocr_callback* (if provided) so the caller can use an AI vision
        model to OCR it.
        
        Args:
            file_path: Path to the PDF file.
            ocr_callback: Optional ``fn(image_bytes, page_label) -> str``
                that performs OCR on a page image and returns extracted text.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            # Fallback to PyPDF2 if PyMuPDF is not installed
            return DocumentProcessor._extract_text_from_pdf_legacy(file_path)
        
        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)
            text_parts: List[str] = []
            ocr_pages: List[int] = []
            
            for page_idx in range(total_pages):
                page = doc[page_idx]
                page_num = page_idx + 1
                page_text = page.get_text().strip()
                
                # Detect image-based pages: very little text but has images
                if len(page_text) < _IMAGE_PAGE_TEXT_THRESHOLD:
                    images = page.get_images()
                    if images and ocr_callback:
                        # Render page to PNG for OCR
                        try:
                            pix = page.get_pixmap(dpi=200)
                            img_bytes = pix.tobytes("png")
                            page_label = f"page {page_num} of {total_pages}"
                            logger.info(
                                f"🔍 Page {page_num}/{total_pages}: only {len(page_text)} chars "
                                f"but has {len(images)} image(s) — sending to OCR"
                            )
                            ocr_text = ocr_callback(img_bytes, page_label)
                            if ocr_text and len(ocr_text.strip()) > len(page_text):
                                page_text = ocr_text.strip()
                                ocr_pages.append(page_num)
                                logger.info(
                                    f"✅ OCR extracted {len(page_text)} chars from page {page_num}"
                                )
                        except Exception as ocr_err:
                            logger.warning(
                                f"⚠️ OCR failed for page {page_num}: {ocr_err}"
                            )
                    elif images:
                        # No callback but we know it's an image page
                        logger.warning(
                            f"⚠️ Page {page_num}/{total_pages}: only {len(page_text)} chars "
                            f"with {len(images)} image(s) — no OCR callback, text may be incomplete"
                        )
                
                if page_text:
                    text_parts.append(
                        f"--- PAGE {page_num} of {total_pages} ---\n{page_text}"
                    )
            
            doc.close()
            
            if ocr_pages:
                logger.info(f"📖 OCR was used on page(s): {ocr_pages}")
            
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"Error extracting text from PDF with PyMuPDF: {e}")
            # Fallback to legacy PyPDF2
            return DocumentProcessor._extract_text_from_pdf_legacy(file_path)
    
    @staticmethod
    def _extract_text_from_pdf_legacy(file_path: str) -> str:
        """Legacy PDF extraction using PyPDF2 (fallback)."""
        import PyPDF2
        try:
            text = []
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                total_pages = len(pdf_reader.pages)
                for i, page in enumerate(pdf_reader.pages, start=1):
                    page_text = page.extract_text()
                    if page_text:
                        text.append(f"--- PAGE {i} of {total_pages} ---\n{page_text}")
            return "\n\n".join(text)
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            return f"[Error reading PDF: {str(e)}]"
    
    @staticmethod
    def extract_text_from_docx(file_path: str) -> str:
        """Extract text from Word document."""
        try:
            doc = Document(file_path)
            paragraphs = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as e:
            print(f"Error extracting text from DOCX: {str(e)}")
            return f"[Error reading DOCX: {str(e)}]"
    
    @staticmethod
    def extract_text_from_txt(file_path: str) -> str:
        """Extract text from plain text file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    return file.read()
            except Exception as e:
                return f"[Error reading text file: {str(e)}]"
        except Exception as e:
            print(f"Error extracting text from TXT: {str(e)}")
            return f"[Error reading text file: {str(e)}]"
    
    @classmethod
    def process_document(
        cls,
        file_path: str,
        file_type: Optional[str] = None,
        ocr_callback: Optional[Callable[[bytes, str], str]] = None,
    ) -> Tuple[str, str]:
        """
        Process a document and extract its text.
        
        Args:
            file_path: Path to the document file
            file_type: Optional file type (will be inferred from extension if not provided)
            ocr_callback: Optional callback ``fn(image_bytes, page_label) -> str``
                for OCR of image-based PDF pages.
            
        Returns:
            Tuple of (extracted_text, detected_file_type)
        """
        # Determine file type
        if not file_type:
            _, ext = os.path.splitext(file_path)
            file_type = ext.lower().lstrip('.')
        
        # Extract text based on file type
        if file_type in ['pdf']:
            text = cls.extract_text_from_pdf(file_path, ocr_callback=ocr_callback)
        elif file_type in ['docx', 'doc']:
            text = cls.extract_text_from_docx(file_path)
        elif file_type in ['txt', 'text']:
            text = cls.extract_text_from_txt(file_path)
        else:
            text = f"[Unsupported file type: {file_type}]"
        
        return text, file_type
    
    @staticmethod
    def validate_file_type(filename: str) -> bool:
        """Check if the file type is supported (documents + video)."""
        allowed_extensions = {'pdf', 'docx', 'doc', 'txt', 'mp4'}
        _, ext = os.path.splitext(filename)
        return ext.lower().lstrip('.') in allowed_extensions

    @staticmethod
    def is_video_file(filename: str) -> bool:
        """Check if the file is a video file (requires Mirabel video analyzer)."""
        video_extensions = {'mp4'}
        _, ext = os.path.splitext(filename)
        return ext.lower().lstrip('.') in video_extensions
