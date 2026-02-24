import pytest
from src.agents.foundry_client import FoundryClient


class DummyResponse:
    def __init__(self, status_code=200, text="", json_dict=None):
        self.status_code = status_code
        self._json = json_dict or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")


def test_derive_model_endpoint_strips_projects_and_rewrites_domain():
    # input has services.ai host and project path
    raw = "https://nextgenagentfoundry.services.ai.azure.com/api/projects/nextgenagents"
    client = FoundryClient(endpoint=raw)
    # internal model endpoint should be cognitiveservices host only
    assert client._model_endpoint == "https://nextgenagentfoundry.cognitiveservices.azure.com"

    # if additional path segments follow the project prefix, they should be removed
    # because chat completion calls always use the base host only.
    raw3 = "https://nextgenagentfoundry.services.ai.azure.com/api/projects/nextgenagents/applications/SchoolAccessIndex/protocols/openai/responses"
    client3 = FoundryClient(endpoint=raw3)
    assert client3._model_endpoint == "https://nextgenagentfoundry.cognitiveservices.azure.com"

    # if given an already-correct URL it should be preserved
    raw2 = "https://nextgenagentfoundry.cognitiveservices.azure.com/"
    client2 = FoundryClient(endpoint=raw2)
    assert client2._model_endpoint == "https://nextgenagentfoundry.cognitiveservices.azure.com"


def test_create_completion_uses_normalized_url(monkeypatch):
    raw = "https://nextgenagentfoundry.services.ai.azure.com/api/projects/nextgenagents"
    client = FoundryClient(endpoint=raw)
    # patch requests.post to capture URL
    called = {}

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        called['url'] = url
        # return a dummy successful response shape
        return DummyResponse(status_code=200, json_dict={"output": "hello"})

    monkeypatch.setattr('src.agents.foundry_client.requests.post', fake_post)
    resp = client.chat.create(model="mydep", messages=[{"role": "user", "content": "hi"}])
    assert called['url'].startswith("https://nextgenagentfoundry.cognitiveservices.azure.com/openai/deployments/mydep")
    assert isinstance(resp.raw, dict)
    assert "output" in resp.raw

    # now test with a suffix path; the URL should still use base host only
    called.clear()
    client_suffix = FoundryClient(endpoint="https://nextgenagentfoundry.services.ai.azure.com/api/projects/nextgenagents/applications/SchoolAccessIndex/protocols/openai/responses")
    resp2 = client_suffix.chat.create(model="moana", messages=[{"role": "user", "content": "hello"}])
    assert called['url'].startswith("https://nextgenagentfoundry.cognitiveservices.azure.com/openai/deployments/moana")
