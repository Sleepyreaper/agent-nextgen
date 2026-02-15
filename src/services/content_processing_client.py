"""Client for calling the Content Processing Solution Accelerator API."""

from typing import Optional, Dict, Any
import requests

from src.logger import app_logger as logger


class ContentProcessingClient:
    """Wrapper for an external content processing service."""

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        api_key_header: str = "x-api-key",
        timeout: int = 30
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.timeout = timeout

    def analyze_text(self, text: str, file_name: str) -> Optional[Dict[str, Any]]:
        if not self.endpoint:
            return None

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.api_key_header] = self.api_key

        payload = {
            "file_name": file_name,
            "text": text,
            "include_raw": True
        }

        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            return None
        except Exception as exc:
            logger.warning(f"Content processing request failed: {exc}")
            return None
