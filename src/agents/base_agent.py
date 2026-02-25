"""Base agent class for Azure AI Foundry agents."""

import json
import logging
import time
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.telemetry import telemetry
from src.config import config
from src.observability import get_tracer, should_capture_sensitive_data
from opentelemetry.trace import SpanKind

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all agents in the system."""
    
    def __init__(self, name: str, client: Any):
        """
        Initialize the base agent.
        
        Args:
            name: The name of the agent
            client: Azure AI client instance (OpenAI or AI Foundry)
        """
        self.name = name
        self.client = client
        self.conversation_history = []
        self._trace_context = {}
    
    @abstractmethod
    async def process(self, message: str) -> str:
        """
        Process a message and return a response.
        
        Args:
            message: The input message to process
            
        Returns:
            The agent's response
        """
        pass
    
    def add_to_history(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content
        })

    def _normalize_response_content(self, response):
        """Ensure any message content on the response is a string.

        Some model adapters (notably Foundry) may parse JSON and set
        `choice.message.content` to a dict/list. Agents expect strings
        and perform text processing (regex, slicing) on the content —
        coercing to a string here avoids downstream type errors.
        """
        try:
            if not response:
                return response
            choices = getattr(response, "choices", None)
            if not choices:
                return response
            for c in choices:
                try:
                    msg = getattr(c, "message", None)
                    if not msg:
                        continue
                    content = getattr(msg, "content", None)
                    if isinstance(content, (dict, list)):
                        try:
                            msg.content = json.dumps(content, ensure_ascii=False)
                        except Exception:
                            msg.content = str(content)
                    elif content is None:
                        msg.content = ""
                    elif not isinstance(content, str):
                        msg.content = str(content)
                except Exception:
                    continue
        except Exception:
            pass
        return response

    def _create_chat_completion(self, operation: str, model: Optional[str] = None, messages: Optional[list] = None, **kwargs):
        """Create a chat completion with OpenTelemetry tracking and multi-pass refinements.

        This function is provider-agnostic and will try common client shapes (Azure/OpenAI style,
        top-level `generate`, or our Foundry adapter). It prefers an explicit `model` argument,
        else falls back to `config.foundry_model_name` when `config.model_provider=='foundry'`,
        otherwise `config.deployment_name` for Azure.
        """
        tracer = get_tracer()
        start_time = time.time()
        response = None

        # Resolve the model to use for this call
        # always prefer an explicit model argument
        # otherwise favour any Foundry deployment name if present, falling
        # back to the Azure deployment.  This ensures that simply having
        # a valid `foundry_model_name` in config will cause agents to hit
        # the Foundry endpoint even if the provider hint was mistakenly
        # left as "azure".
        resolved_model = model or config.foundry_model_name or config.deployment_name

        # decide telemetry/system tag based on provider (not model name)
        system_name = "azure_openai"
        if config.model_provider and config.model_provider.lower() == "foundry":
            system_name = "foundry"

        # log what we resolved so failures are easier to diagnose
        logger.debug("Resolved model for agent %s: provider=%s resolved_model=%s", self.name, config.model_provider, resolved_model)

        try:
            if tracer:
                with tracer.start_as_current_span(f"chat {resolved_model or 'unknown'}", kind=SpanKind.CLIENT) as span:
                    span.set_attribute("gen_ai.system", system_name)
                    span.set_attribute("gen_ai.request.model", resolved_model or "")
                    span.set_attribute("gen_ai.operation.name", "chat")
                    span.set_attribute("gen_ai.agent.id", self.name.lower().replace(" ", "-"))
                    span.set_attribute("gen_ai.agent.name", self.name)

                    # Request parameters
                    max_tokens = kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
                    if max_tokens is not None:
                        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))

                    temperature = kwargs.get("temperature")
                    if temperature is not None:
                        span.set_attribute("gen_ai.request.temperature", float(temperature))

                    top_p = kwargs.get("top_p")
                    if top_p is not None:
                        span.set_attribute("gen_ai.request.top_p", float(top_p))

                    for key, value in self._trace_context.items():
                        if value is not None:
                            span.set_attribute(f"app.{key}", str(value))

                    if should_capture_sensitive_data():
                        try:
                            span.set_attribute("gen_ai.prompt", json.dumps(messages, ensure_ascii=True)[:2000])
                        except Exception:
                            pass

                    refinements = int(kwargs.pop("refinements", 2))
                    refinement_instruction = kwargs.pop("refinement_instruction", None)

                    def _single_call(msgs, call_kwargs):
                        # Flexible resolver: try several method paths and callables
                        tried = []

                        def _serialize_for_input(m):
                            if not m:
                                return ""
                            try:
                                if isinstance(m, str):
                                    return m
                                if isinstance(m, list):
                                    parts = []
                                    for item in m:
                                        role = item.get("role", "user")
                                        content = item.get("content", "")
                                        parts.append(f"[{role}] {content}")
                                    return "\n\n".join(parts)
                                return str(m)
                            except Exception:
                                return str(m)

                        def _attempt_callable(obj, msgs, call_kwargs):
                            """Try a variety of common signatures against a callable object.

                            Returns the response object on success or None.
                            """
                            if not callable(obj):
                                return None

                            serialized = _serialize_for_input(msgs)

                            attempts = [
                                ("model_messages_kw", lambda: obj(model=resolved_model, messages=msgs, **call_kwargs)),
                                ("model_input_kw", lambda: obj(model=resolved_model, input=serialized, **call_kwargs)),
                                ("model_prompt_kw", lambda: obj(model=resolved_model, prompt=serialized, **call_kwargs)),
                                ("messages_kw", lambda: obj(messages=msgs, **call_kwargs)),
                                ("input_kw", lambda: obj(input=serialized, **call_kwargs)),
                                ("prompt_kw", lambda: obj(prompt=serialized, **call_kwargs)),
                                ("positional_model_msgs", lambda: obj(resolved_model, msgs, **call_kwargs)),
                                ("positional_prompt", lambda: obj(serialized, **call_kwargs)),
                                ("single_positional", lambda: obj(msgs, **call_kwargs)),
                            ]

                            for name, fn in attempts:
                                try:
                                    logger.debug("Attempting callable signature %s on %s", name, getattr(obj, '__name__', type(obj)))
                                    resp = fn()
                                    if resp is not None:
                                        logger.debug("Callable signature %s succeeded", name)
                                        return resp
                                except TypeError:
                                    # signature mismatch; try next
                                    continue
                                except Exception as e:
                                    # Some SDKs raise structured exceptions; log debug and continue
                                    logger.debug("Callable signature %s raised exception: %s", name, e)
                                    continue
                            return None

                        def _resolve_and_call(path: str):
                            """Resolve dotted path like 'chat.create' on self.client and call if callable."""
                            parts = path.split('.')
                            obj = self.client
                            for p in parts:
                                if not hasattr(obj, p):
                                    return None
                                obj = getattr(obj, p)
                            # If object is a client-like container that itself is callable
                            return _attempt_callable(obj, msgs, call_kwargs)

                        # Candidate paths in preferred order (extended)
                        candidates = [
                            'chat.create',
                            'chat.completions.create',
                            'chat.completions',
                            'chat',  # callable chat(...) signature
                            'responses.create',
                            'responses',
                            'generate',
                            'completions.create',
                            'completions',
                            'create',
                        ]

                        for c in candidates:
                            try:
                                resp = _resolve_and_call(c)
                                tried.append(c)
                                if resp is not None:
                                    logger.debug("Model call succeeded using '%s'", c)
                                    return resp
                            except Exception as e:
                                logger.debug("Candidate '%s' raised exception: %s", c, e)

                        logger.debug("Tried candidate call paths: %s", tried)
                        # Final fallback: probe likely callable attributes on the client
                        logger.warning("No candidate path matched; probing client for callable entrypoints. Client type: %s", type(self.client))
                        tried_probe = []
                        for name in dir(self.client):
                            lname = name.lower()
                            if not any(k in lname for k in ("chat", "generate", "completion", "complete", "predict")):
                                continue
                            try:
                                attr = getattr(self.client, name)
                                if callable(attr):
                                    tried_probe.append(name)
                                    logger.debug("Probing callable attribute '%s'", name)
                                    # Try keyword then positional args
                                    try:
                                        resp = attr(model=resolved_model, messages=msgs, **call_kwargs)
                                        if resp is not None:
                                            logger.debug("Callable probe '%s' succeeded", name)
                                            return resp
                                    except TypeError:
                                        try:
                                            resp = attr(resolved_model, msgs, **call_kwargs)
                                            if resp is not None:
                                                logger.debug("Callable probe (positional) '%s' succeeded", name)
                                                return resp
                                        except Exception:
                                            logger.debug("Callable probe '%s' raised", name, exc_info=True)
                                    except Exception:
                                        logger.debug("Callable probe '%s' raised", name, exc_info=True)
                            except Exception:
                                continue

                        logger.debug("Probed attributes: %s", tried_probe)
                        # Emit an explicit error log with client type and a
                        # short repr to help diagnose why no callable entrypoint
                        # matched in production.
                        try:
                            client_type = type(self.client)
                            client_repr = repr(self.client)
                        except Exception:
                            client_type = None
                            client_repr = "<unrepresentable>"
                        logger.error(
                            "No compatible model call method found on client. agent=%s client_type=%s client_repr=%s tried_paths=%s probed=%s",
                            self.name,
                            client_type,
                            client_repr[:200],
                            tried,
                            tried_probe,
                        )
                        raise RuntimeError("No compatible model call method found on client")

                    # First call
                    # Runtime introspection: log the concrete client type and
                    # any attributes that look like model entrypoints. This
                    # helps diagnose mismatches between the adapter and the
                    # resolver in the deployed environment.
                    try:
                        client_type = type(self.client)
                        candidate_attrs = [
                            a for a in dir(self.client)
                            if any(k in a.lower() for k in ("chat", "generate", "completion", "complete", "predict", "completions"))
                        ]
                        logger.info("Model client introspect: type=%s candidate_attrs=%s", client_type, candidate_attrs)
                    except Exception:
                        logger.exception("Failed to introspect model client before call")

                    response = _single_call(messages or [], kwargs)

                    # Refinement passes
                    for _ in range(1, refinements):
                        try:
                            prev_content = ""
                            try:
                                prev_content = response.choices[0].message.content if getattr(response, "choices", None) else ""
                            except Exception:
                                prev_content = str(getattr(response, "raw", response))

                            refinement_msgs = []
                            for m in (messages or []):
                                refinement_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
                            refinement_msgs.append({"role": "assistant", "content": prev_content})
                            instr = refinement_instruction or "Refine and improve the previous assistant response for accuracy, completeness, and clarity. Keep the same output format unless asked otherwise."
                            refinement_msgs.append({"role": "user", "content": instr})

                            response = _single_call(refinement_msgs, kwargs)
                        except Exception:
                            break

                    # Telemetry: latency & usage (GenAI Semantic Conventions)
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("gen_ai.client.operation.duration_ms", duration_ms)

                    usage = getattr(response, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", None)
                        output_tokens = getattr(usage, "completion_tokens", None)
                        total_tokens = getattr(usage, "total_tokens", None)
                        if input_tokens is not None:
                            span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
                        if output_tokens is not None:
                            span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
                        if total_tokens is not None:
                            span.set_attribute("gen_ai.usage.total_tokens", int(total_tokens))

                        telemetry.log_model_call(
                            model=resolved_model,
                            input_tokens=input_tokens or 0,
                            output_tokens=output_tokens or 0,
                            duration_ms=duration_ms,
                            success=True
                        )

                    # Capture response ID (GenAI Semantic Convention)
                    response_id = getattr(response, "id", None)
                    if response_id:
                        span.set_attribute("gen_ai.response.id", str(response_id))

                    # Optionally capture response content
                    if should_capture_sensitive_data():
                        try:
                            content = response.choices[0].message.content if getattr(response, "choices", None) else ""
                            span.set_attribute("gen_ai.response.text", str(content)[:2000])
                        except Exception:
                            pass

                    # Normalize content to string to avoid downstream type errors
                    try:
                        response = self._normalize_response_content(response)
                    except Exception:
                        pass

                    return response

            else:
                # No tracer: still make calls with same logic
                refinements = int(kwargs.pop("refinements", 2))
                refinement_instruction = kwargs.pop("refinement_instruction", None)

                def _single_call_no_trace(msgs, call_kwargs):
                    # Use the same flexible resolver as above (no tracing)
                    def _resolve_and_call_no_trace(path: str):
                        parts = path.split('.')
                        obj = self.client
                        for p in parts:
                            if not hasattr(obj, p):
                                return None
                            obj = getattr(obj, p)
                        if callable(obj):
                            try:
                                return obj(model=resolved_model, messages=msgs, **call_kwargs)
                            except TypeError:
                                try:
                                    return obj(resolved_model, msgs, **call_kwargs)
                                except Exception:
                                    raise
                        return None

                    candidates = [
                        'chat.create',
                        'chat.completions.create',
                        'chat',
                        'generate',
                        'completions.create',
                        'completions'
                    ]
                    for c in candidates:
                        resp = _resolve_and_call_no_trace(c)
                        if resp is not None:
                            return resp
                    # No candidate matched; perform the same safe probing as above
                    logger.warning("No candidate path matched (no tracer); probing client for callable entrypoints. Client type: %s", type(self.client))
                    tried_probe = []
                    for name in dir(self.client):
                        lname = name.lower()
                        if not any(k in lname for k in ("chat", "generate", "completion", "complete", "predict")):
                            continue
                        try:
                            attr = getattr(self.client, name)
                            if callable(attr):
                                tried_probe.append(name)
                                logger.debug("Probing callable attribute '%s' (no-trace)", name)
                                try:
                                    resp = attr(model=resolved_model, messages=msgs, **call_kwargs)
                                    if resp is not None:
                                        logger.debug("Callable probe '%s' succeeded (no-trace)", name)
                                        return resp
                                except TypeError:
                                    try:
                                        resp = attr(resolved_model, msgs, **call_kwargs)
                                        if resp is not None:
                                            logger.debug("Callable probe (positional) '%s' succeeded (no-trace)", name)
                                            return resp
                                    except Exception:
                                        logger.debug("Callable probe '%s' raised (no-trace)", name, exc_info=True)
                                except Exception:
                                    logger.debug("Callable probe '%s' raised (no-trace)", name, exc_info=True)
                        except Exception:
                            continue

                    logger.debug("Probed attributes (no-trace): %s", tried_probe)
                    try:
                        client_type = type(self.client)
                        client_repr = repr(self.client)
                    except Exception:
                        client_type = None
                        client_repr = "<unrepresentable>"
                    logger.error(
                        "No compatible model call method found on client (no-trace). agent=%s client_type=%s client_repr=%s tried_paths=%s probed=%s",
                        self.name,
                        client_type,
                        client_repr[:200],
                        candidates,
                        tried_probe,
                    )
                    raise RuntimeError("No compatible model call method found on client")

                # Runtime introspection for no-tracer path as well
                try:
                    client_type = type(self.client)
                    candidate_attrs = [
                        a for a in dir(self.client)
                        if any(k in a.lower() for k in ("chat", "generate", "completion", "complete", "predict", "completions"))
                    ]
                    logger.info("Model client introspect (no-trace): type=%s candidate_attrs=%s", client_type, candidate_attrs)
                except Exception:
                    logger.exception("Failed to introspect model client (no-trace) before call")

                response = _single_call_no_trace(messages or [], kwargs)
                for _ in range(1, refinements):
                    try:
                        prev_content = ""
                        try:
                            prev_content = response.choices[0].message.content if getattr(response, "choices", None) else ""
                        except Exception:
                            prev_content = str(getattr(response, "raw", response))

                        refinement_msgs = []
                        for m in (messages or []):
                            refinement_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
                        refinement_msgs.append({"role": "assistant", "content": prev_content})
                        instr = refinement_instruction or "Refine and improve the previous assistant response for accuracy, completeness, and clarity. Keep the same output format unless asked otherwise."
                        refinement_msgs.append({"role": "user", "content": instr})

                        response = _single_call_no_trace(refinement_msgs, kwargs)
                    except Exception:
                        break

                # Ensure content is stringified for callers
                try:
                    response = self._normalize_response_content(response)
                except Exception:
                    pass

                return response

        except Exception as e:
            endpoint = getattr(self.client, "azure_endpoint", None) or getattr(self.client, "base_url", None) or getattr(self.client, "endpoint", None)
            endpoint_host = None
            if isinstance(endpoint, str) and endpoint:
                try:
                    endpoint_host = urlparse(endpoint).netloc or endpoint
                except Exception:
                    endpoint_host = endpoint

            api_version = getattr(self.client, "api_version", None)
            telemetry.track_event(
                "model_call_error",
                properties={
                    "agent_name": self.name,
                    "model": resolved_model or "",
                    "operation": operation,
                    "api_version": str(api_version) if api_version else "",
                    "endpoint_host": endpoint_host or "",
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )
            logger.warning(
                "Model call failed",
                extra={
                    "agent_name": self.name,
                    "model": resolved_model,
                    "operation": operation,
                    "api_version": api_version,
                    "endpoint_host": endpoint_host,
                    "error": str(e),
                }
            )
            # Log error to telemetry
            try:
                telemetry.log_model_call(
                    model=resolved_model,
                    input_tokens=0,
                    output_tokens=0,
                    duration_ms=int((time.time() - start_time) * 1000),
                    success=False
                )
            except Exception:
                pass
            raise

    def two_step_query_format(
        self,
        operation_base: str,
        model: Optional[str],
        query_messages: list,
        format_messages_template,
        query_kwargs: dict = None,
        format_kwargs: dict = None,
    ):
        """Perform a two-step model interaction:

        1) Run a focused "query" pass to locate or extract the needed facts.
        2) Run a "format" pass which receives the query output and produces
           the final structured/verbosity-controlled result.

        The `format_messages_template` may be either a list of message dicts
        (each with `role` and `content`) where the token "{found}" will be
        replaced with the query output, or a single string template which will
        be injected into a single user message.
        Returns a tuple `(query_response, format_response)` where each is the
        raw response object returned by `_create_chat_completion`.
        """
        query_kwargs = query_kwargs or {}
        format_kwargs = format_kwargs or {}

        # Query pass
        q_resp = self._create_chat_completion(
            operation=f"{operation_base}.query",
            model=model,
            messages=query_messages,
            **query_kwargs,
        )

        # Extract textual content from query response in a best-effort way
        try:
            q_content = q_resp.choices[0].message.content if getattr(q_resp, "choices", None) else str(getattr(q_resp, "raw", q_resp))
        except Exception:
            q_content = str(q_resp)

        # Build format messages by injecting q_content into the template
        fmt_msgs = []
        if isinstance(format_messages_template, list):
            for m in format_messages_template:
                content = m.get("content", "")
                try:
                    content = content.replace("{found}", q_content)
                except Exception:
                    pass
                fmt_msgs.append({
                    "role": m.get("role", "user"),
                    "content": content
                })
        else:
            # single-string template
            try:
                content = format_messages_template.format(found=q_content)
            except Exception:
                content = format_messages_template.replace("{found}", q_content)
            fmt_msgs = [
                {"role": "user", "content": content}
            ]

        f_resp = self._create_chat_completion(
            operation=f"{operation_base}.format",
            model=model,
            messages=fmt_msgs,
            **format_kwargs,
        )

        return q_resp, f_resp

    def set_trace_context(
        self,
        application_id: Optional[Any] = None,
        student_id: Optional[Any] = None,
        applicant_name: Optional[str] = None
    ) -> None:
        self._trace_context = {
            "app.application_id": application_id,
            "app.student_id": student_id,
            "app.applicant_name": applicant_name
        }

    def clear_trace_context(self) -> None:
        self._trace_context = {}
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
