"""Document processing utilities for extracting text from various file formats."""

import os
from typing import Tuple, Optional
import PyPDF2
from docx import Document


class DocumentProcessor:
    """Process and extract text from uploaded documents."""
    
    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        """Extract text from PDF file."""
        try:
            text = []
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
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
    def process_document(cls, file_path: str, file_type: Optional[str] = None) -> Tuple[str, str]:
        """
        Process a document and extract its text.
        
        Args:
            file_path: Path to the document file
            file_type: Optional file type (will be inferred from extension if not provided)
            
        Returns:
            Tuple of (extracted_text, detected_file_type)
        """
        # Determine file type
        if not file_type:
            _, ext = os.path.splitext(file_path)
            file_type = ext.lower().lstrip('.')
        
        # Extract text based on file type
        if file_type in ['pdf']:
            text = cls.extract_text_from_pdf(file_path)
        elif file_type in ['docx', 'doc']:
            text = cls.extract_text_from_docx(file_path)
        elif file_type in ['txt', 'text']:
            text = cls.extract_text_from_txt(file_path)
        else:
            text = f"[Unsupported file type: {file_type}]"
        
        return text, file_type
    
    @staticmethod
    def validate_file_type(filename: str) -> bool:
        """Check if the file type is supported."""
        allowed_extensions = {'pdf', 'docx', 'doc', 'txt'}
        _, ext = os.path.splitext(filename)
        return ext.lower().lstrip('.') in allowed_extensions
