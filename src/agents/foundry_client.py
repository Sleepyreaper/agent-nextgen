"""Lightweight adapter for calling an AI Foundry model deployment (gpt-4.1).

This adapter exposes a minimal interface compatible with existing BaseAgent
usage: `client.chat.completions.create(model=..., messages=..., **kwargs)`.

The implementation is intentionally conservative and tolerant: it will
attempt an HTTP POST to the configured Foundry endpoint using an API key
and translate responses into an OpenAI-like object with `choices[0].message.content`.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse
import re
try:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    AZURE_IDENTITY_AVAILABLE = True
except Exception:
    DefaultAzureCredential = None
    get_bearer_token_provider = None
    AZURE_IDENTITY_AVAILABLE = False

try:
    # Prefer using the OpenAI Python SDK when available so we can pass
    # a bearer token provider directly (Entra ID) as the `api_key` parameter
    # which many Azure/OpenAI-compatible SDKs support.
    from openai import OpenAI
    OPENAI_SDK_AVAILABLE = True
except Exception:
    OpenAI = None
    OPENAI_SDK_AVAILABLE = False

from src.config import config

logger = logging.getLogger(__name__)


class _SimpleChoice:
    def __init__(self, text: str):
        self.message = type("M", (), {"content": text})()


class _SimpleResponse:
    def __init__(self, text: str, raw: Dict[str, Any]):
        self.choices = [_SimpleChoice(text)]
        self.raw = raw


class FoundryChatCompletions:
    def __init__(self, base_client: "FoundryClient"):
        self._client = base_client

    def create(self, model: Optional[str] = None, messages: Optional[List[Dict[str, Any]]] = None, **kwargs):
        return self._client._create_completion_request(model=model, messages=messages, **kwargs)
    
    @property
    def completions(self):
        """Compatibility alias so callers can use `chat.completions.create(...)`.

        Some code paths expect `client.chat.completions.create(...)` (Azure/OpenAI
        style). Expose `completions` as an alias to this object so those calls
        work against the Foundry adapter.
        """
        return self


class FoundryClient:
    """A minimal HTTP adapter to call a Foundry model endpoint.

    Notes:
    - The real Foundry API may differ; this wrapper provides a stable interface
      for the codebase and documents required parameters.
    - Required config values:
      - `config.foundry_project_endpoint`: base URL for Foundry model service
        (used for dataset/project API calls; may include "/api/projects/..."
        path).
      - `config.foundry_api_key`: API key or token for Authorization header
    - `config.foundry_model_name`: model id (e.g. gpt-4.1)

    This class will internally normalize the provided endpoint so that model
    calls always go to an appropriate OpenAI-style host (typically the
    cognitiveservices.azure.com domain).  This prevents misconfigured values
    like the legacy *services.ai.azure.com* project URL from being used
    directly in chat completion requests.
    """

    def _derive_model_endpoint(self, ep: Optional[str]) -> Optional[str]:
        """Convert a configured project endpoint into a base URL suitable
        for OpenAI-style chat completion requests.

        - If the endpoint contains a ".services.ai.azure.com" host we
          rewrite it to the corresponding ".cognitiveservices.azure.com"
          host, which is what the OpenAI API expects.
        - Remove the leading "/api/projects/{project}" segment if present,
          but retain any further path suffix (e.g. custom protocol paths
          used by Moana/Naveen).  This allows callers to supply either a
          generic project root or a more specific sub-URL without losing
          the extra information.
        """
        if not ep:
            return ep
        try:
            parsed = urlparse(ep)
            host = parsed.netloc
            # rewrite host if using the older services.ai domain
            if ".services.ai.azure.com" in host:
                host = host.replace(".services.ai.azure.com", ".cognitiveservices.azure.com")

            # ignore any path component completely; chat completion
            # requests should always go to the host root.  This avoids
            # mistakenly appending /applications/SchoolAccessIndex or other
            # protocol-specific subpaths that are not valid for model calls.
            return f"{parsed.scheme}://{host}"
        except Exception:
            # be defensive; if parsing fails just return original
            return ep

    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None):
        # ``endpoint`` may be a Foundry project URL (including
        # "/api/projects/..." path) or the more generic Azure OpenAI
        # base URL.  We retain the original value in ``self.endpoint`` for
        # any dataset/project operations, but compute a normalized
        # ``_model_endpoint`` that is safe to use when constructing
        # `/openai/deployments/...` paths.  This shields callers from
        # misconfigured envvars such as the old *services.ai.azure.com* URL
        # which should instead target the cognitiveservices host.
        self.endpoint = endpoint or config.foundry_project_endpoint
        self._model_endpoint = self._derive_model_endpoint(self.endpoint)

        self.api_key = api_key or config.foundry_api_key
        # Preferred api_version: explicit env override, then config.foundry_api_version, then sensible default
        self._api_version = os.getenv('FOUNDRY_API_VERSION') or getattr(config, 'foundry_api_version', None) or '2024-05-01-preview'
        self.chat = FoundryChatCompletions(self)
        self._openai_client = None

        # If OpenAI SDK and Azure identity are available, try to construct
        # an SDK client that can use Entra ID (managed identity) tokens.
        try:
            if OPENAI_SDK_AVAILABLE:
                if self.api_key:
                    # If an API key/string is configured, use it with SDK.
                    # Provide api_version when available so the SDK will append
                    # `api-version` as a query parameter for Azure/Foundry endpoints.
                    if self._api_version:
                        self._openai_client = OpenAI(base_url=self.endpoint, api_key=self.api_key, api_version=self._api_version)
                    else:
                        self._openai_client = OpenAI(base_url=self.endpoint, api_key=self.api_key)
                elif AZURE_IDENTITY_AVAILABLE and get_bearer_token_provider is not None:
                    # Prefer the ai.azure.com audience which some Foundry endpoints require.
                    try:
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
                        if self._api_version:
                            self._openai_client = OpenAI(base_url=self.endpoint, api_key=token_provider, api_version=self._api_version)
                        else:
                            self._openai_client = OpenAI(base_url=self.endpoint, api_key=token_provider)
                    except Exception:
                        # Fallback to cognitiveservices audience
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
                        if self._api_version:
                            self._openai_client = OpenAI(base_url=self.endpoint, api_key=token_provider, api_version=self._api_version)
                        else:
                            self._openai_client = OpenAI(base_url=self.endpoint, api_key=token_provider)
        except Exception:
            # If SDK init fails for any reason, fall back to HTTP requests path.
            logger.debug("OpenAI SDK client initialization failed; falling back to requests-based client", exc_info=True)

            # Configure a requests Session with retries and backoff for HTTP fallback.
            try:
                self._session = requests.Session()
                retries = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(['POST', 'GET']))
                adapter = HTTPAdapter(max_retries=retries)
                self._session.mount('https://', adapter)
                self._session.mount('http://', adapter)
            except Exception:
                self._session = None

    def _serialize_messages(self, messages: Optional[List[Dict[str, str]]]) -> str:
        if not messages:
            return ""
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"[{role}] {content}")
        return "\n\n".join(parts)

    @staticmethod
    def _coerce_messages_for_http(messages: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Coerce message content to primitive strings for the HTTP fallback.

        The raw HTTP path sends JSON directly to the Foundry REST API which
        may reject non-string ``content`` values (e.g. multimodal list-of-dicts).
        For multimodal messages we extract the text portions and drop image data
        since the HTTP path cannot reliably pass binary payloads.
        """
        if not messages:
            return messages
        import copy
        coerced = copy.deepcopy(messages)
        for msg in coerced:
            if msg is None:
                continue
            content = msg.get("content")
            if content is not None and not isinstance(content, str):
                if isinstance(content, list):
                    # Multimodal content: extract text parts, note image presence
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                text_parts.append("[image attached]")
                    msg["content"] = "\n".join(text_parts) if text_parts else json.dumps(content)
                else:
                    try:
                        msg["content"] = json.dumps(content)
                    except Exception:
                        msg["content"] = str(content)
                logger.debug("[Foundry] coerced non-str message content for HTTP path")
        return coerced

    def _create_completion_request(self, model: Optional[str], messages: Optional[List[Dict[str, Any]]], **kwargs):
        if not self.endpoint:
            raise RuntimeError("Foundry endpoint not configured (config.foundry_project_endpoint)")
        # start with the normalized model endpoint when building the URL
        base = self._model_endpoint or self.endpoint

        # Build OpenAI-compatible deployment URL (chat completions)
        deployment = model or config.foundry_model_name
        url = base.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions"

        # If we have an OpenAI SDK client available that was initialized
        # with a bearer token provider, prefer using it — it will handle
        # token refresh and wiring for Entra ID automatically.
        # NOTE: we do NOT coerce message content before the SDK path because
        # the OpenAI SDK natively supports multimodal messages (list-of-dicts
        # content with image_url, etc.).  See _coerce_messages_for_http()
        # for the HTTP fallback path which requires plain-string content.
        if self._openai_client is not None:
            try:
                client_resp = self._openai_client.chat.completions.create(model=deployment, messages=messages or [], **kwargs)
                # The SDK returns an object with .choices where each choice
                # contains a `message` with `content` (OpenAI-compatible).
                text = ''
                try:
                    if hasattr(client_resp, 'choices') and client_resp.choices:
                        c0 = client_resp.choices[0]
                        # debug info about SDK call
                        logger.info("[Foundry] _create_completion_request called: model=%s, endpoint=%s, messages=%s, kwargs=%s", model, self.endpoint, json.dumps(messages)[:1000], str(kwargs))
                        # Some SDK versions expose nested `message.content` or `text`
                        text = getattr(getattr(c0, 'message', None), 'content', None) or getattr(c0, 'text', None) or str(c0)
                    else:
                        # Fallback to stringifying the raw object
                        text = str(client_resp)
                except Exception:
                    text = str(client_resp)

                # If possible, get raw JSON-like shape
                raw = None
                try:
                    raw = client_resp.to_dict() if hasattr(client_resp, 'to_dict') else client_resp
                except Exception:
                    raw = client_resp

                return _SimpleResponse(text=text, raw=raw)
            except Exception:
                # If the SDK call failed, log and continue to the HTTP fallback
                logger.exception("OpenAI SDK call failed; falling back to HTTP requests-based call")
        # Try a short list of candidate api-version values so the adapter can
        # work against Foundry variants without requiring an immediate redeploy
        # of app settings. Order: explicit Foundry env override, explicit
        # Key Vault/configured Foundry api-version, generic configured API
        # version, then sensible fallbacks.
        candidates = []
        # Allow an explicit override specifically for Foundry
        foundry_env = os.getenv('FOUNDRY_API_VERSION') or os.getenv('AZURE_API_VERSION')
        if foundry_env:
            candidates.append(foundry_env)

        # Prefer a Foundry-specific api-version from Key Vault/config
        cfg_foundry = getattr(config, 'foundry_api_version', None)
        if cfg_foundry:
            candidates.append(cfg_foundry)

        # Fall back to the generic configured API version (if set)
        cfg_api = getattr(config, 'api_version', None)
        if cfg_api:
            candidates.append(cfg_api)

        # Common Foundry/OpenAI-compatible API versions to try
        candidates.extend(['2025-10-01', '2024-10-21', '2024-05-01-preview'])

        last_error = None

        payload: Dict[str, Any] = {}
        # Many Foundry APIs expect a single text input; join messages conservatively.
        prompt = self._serialize_messages(messages)
        # Do NOT include a top-level `model` when calling a deployment-specific
        # URL (e.g. /openai/deployments/{deployment}/...). Some Foundry/Azure
        # endpoints reject unknown fields. We will include `model` only when
        # trying alternative OpenAI-style paths that expect it.

        # Provide multiple compatibility shapes so different Foundry model versions
        # (v2/v3, deepseek variants) can accept at least one of these fields. Be
        # conservative: if callers pass a `messages` structure (chat-style), do
        # NOT include `input`/`inputs` fields since strict Foundry variants will
        # reject unknown fields.
        if messages is None:
            payload["input"] = prompt
            # Some Foundry APIs expect an `inputs` array of dicts
            payload["inputs"] = [{"text": prompt}] if prompt else []
        else:
            # Coerce multimodal content to strings for the HTTP fallback path.
            # The OpenAI SDK path (above) preserves multimodal format natively.
            payload["messages"] = self._coerce_messages_for_http(messages)

        # Pass-through of common parameters where supported
        for k in ("temperature", "max_completion_tokens", "max_tokens", "top_p", "n"):
            if k in kwargs:
                payload[k] = kwargs[k]

        headers = {"Content-Type": "application/json"}

        # Prefer explicit API key when provided; otherwise, attempt to acquire
        # an Azure AD access token via DefaultAzureCredential (managed identity
        # or service principal) if the azure-identity package is available.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            if AZURE_IDENTITY_AVAILABLE:
                try:
                    cred = DefaultAzureCredential()

                    # Prefer the ai.azure.com audience which the Foundry endpoint
                    # indicated it expects. Fall back to cognitiveservices if needed.
                    token = None
                    try:
                        t = cred.get_token("https://ai.azure.com/.default")
                        if t and getattr(t, "token", None):
                            token = t
                            logger.info("Acquired AAD token for Foundry endpoint (scope=%s) [redacted]", "https://ai.azure.com/.default")
                    except Exception:
                        try:
                            t = cred.get_token("https://cognitiveservices.azure.com/.default")
                            if t and getattr(t, "token", None):
                                token = t
                                logger.info("Acquired AAD token for Foundry endpoint (scope=%s) [redacted]", "https://cognitiveservices.azure.com/.default")
                        except Exception:
                            logger.debug("AAD token acquisition fallback failed", exc_info=True)

                    if token:
                        headers["Authorization"] = f"Bearer {token.token}"
                except Exception:
                    logger.exception("Failed to acquire AAD token for Foundry endpoint; continuing without token")

        # Log the payload and safe headers to aid debugging on App Service.
        try:
            safe_headers = headers.copy()
            if "Authorization" in safe_headers:
                safe_headers["Authorization"] = "<redacted>"
            logger.info("Foundry request url=%s headers=%s payload=%s", url, safe_headers, json.dumps(payload)[:2000])

            # Try each candidate api-version until we get a non-400/"API version"
            # error or a successful response.
            resp = None
            api_version_rejected = False
            for ver in candidates:
                params = {'api-version': ver}
                try:
                    session = self._session or requests
                    timeout = kwargs.get('timeout', 60)
                    resp = session.post(url, headers=headers, json=payload, params=params, timeout=timeout)
                except Exception as e:
                    last_error = e
                    logger.warning("Foundry request attempt failed (ver=%s): exception=%s", ver, e)
                    continue

                # If success, break and parse
                if resp.status_code >= 200 and resp.status_code < 300:
                    break

                # If API version not supported, try next candidate
                body_text = ''
                try:
                    body_text = resp.text or ''
                except Exception:
                    body_text = ''

                if resp.status_code == 400 and 'API version' in body_text:
                    last_error = body_text
                    api_version_rejected = True
                    logger.warning("Foundry rejected api-version=%s body=%s", ver, body_text[:2000])
                    continue

                # For any other status (including PermissionDenied 401), stop and raise
                last_error = body_text or resp.status_code
                logger.warning("Foundry request attempt returned status=%s for api-version=%s body=%s", resp.status_code, ver, body_text[:2000])
                break

            # If all api-version candidates were rejected specifically for api-version,
            # attempt one or more alternative OpenAI-style paths that different
            # Foundry deployments may accept.
            if (resp is None or (api_version_rejected and getattr(resp, 'status_code', 0) >= 400)):
                alt_payload = {'model': deployment}
                if messages is not None:
                    alt_payload['messages'] = messages
                alt_payload.update({k: v for k, v in payload.items() if k in ('temperature', 'max_tokens', 'top_p', 'n')})

                alt_urls = []
                # Directly under configured endpoint
                alt_urls.append(self.endpoint.rstrip('/') + '/openai/v1/chat/completions')

                # Try host-root (strip any /api/projects/... path)
                try:
                    parsed = urlparse(self.endpoint)
                    host_root = f"{parsed.scheme}://{parsed.netloc}"
                    alt_urls.append(host_root + '/openai/v1/chat/completions')
                    alt_urls.append(host_root + f"/openai/deployments/{deployment}/chat/completions")
                except Exception:
                    pass

                # If endpoint contains /api/projects/{proj}, try trimming that segment
                if '/api/projects/' in self.endpoint:
                    try:
                        trimmed = re.sub(r'/api/projects/[^/]+', '', self.endpoint.rstrip('/'))
                        alt_urls.append(trimmed + '/openai/v1/chat/completions')
                        alt_urls.append(trimmed + f"/openai/deployments/{deployment}/chat/completions")
                    except Exception:
                        pass

                # Try each alt URL until one succeeds
                for alt_url in alt_urls:
                    try:
                        logger.info('Attempting alternative OpenAI-style path url=%s headers=%s payload=%s', alt_url, {'Authorization': '<redacted>' if 'Authorization' in headers else None}, str(alt_payload)[:1000])
                        session = self._session or requests
                        timeout = kwargs.get('timeout', 60)
                        resp = session.post(alt_url, headers=headers, json=alt_payload, timeout=timeout)
                        if resp is not None and 200 <= getattr(resp, 'status_code', 0) < 300:
                            break
                    except Exception as e:
                        last_error = e

            if resp is None:
                raise RuntimeError(f"No response from Foundry endpoint; last error={last_error}")

            # sometimes the default deployment name (e.g. "gpt-4.1") isn't
            # actually created in the project; if we get a 404 and we were using
            # the configured model name, retry once with a preview suffix.
            if resp is not None and getattr(resp, 'status_code', 0) == 404:
                # deployment variable may have been mutated above; compare to
                # the original request model or config value so we only retry
                orig = model or config.foundry_model_name
                if orig and orig == deployment and orig == 'gpt-4.1':
                    alt = orig + '-preview'
                    logger.warning("Foundry deployment '%s' not found; retrying with '%s'", orig, alt)
                    # recursive call should exercise same http logic with alt name
                    return self._create_completion_request(alt, messages, **kwargs)
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                body_text = None
                try:
                    body_text = resp.text
                except Exception:
                    body_text = "<unreadable>"
                logger.error("Foundry request failed: status=%s url=%s body=%s", getattr(resp, 'status_code', None), url, body_text)
                resp.raise_for_status()

            raw = resp.json()

            # Best-effort extraction of text from common response shapes.
            text = ""
            # Example: {"output": "..."}
            if isinstance(raw, dict):
                if "output" in raw and isinstance(raw["output"], str):
                    text = raw["output"]
                elif "outputs" in raw and isinstance(raw["outputs"], list) and raw["outputs"]:
                    # outputs could be list of dicts with 'text' or 'content'
                    first = raw["outputs"][0]
                    if isinstance(first, dict):
                        text = first.get("text") or first.get("content") or json.dumps(first)
                    else:
                        text = str(first)
                elif "choices" in raw and isinstance(raw["choices"], list) and raw["choices"]:
                    c0 = raw["choices"][0]
                    if isinstance(c0, dict):
                        msg = c0.get("message")
                        if isinstance(msg, dict):
                            text = msg.get("content") or json.dumps(msg)
                        elif isinstance(msg, str):
                            text = msg
                        else:
                            text = c0.get("text") or json.dumps(c0)
                    else:
                        text = str(c0)
                else:
                    # Fall back to stringifying the entire response
                    text = json.dumps(raw)
            else:
                text = str(raw)

            return _SimpleResponse(text=text, raw=raw)

        except Exception as e:
            logger.exception("Foundry model call failed: %s", e)
            raise
