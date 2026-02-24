import os
from src.config import config

def test_foundry_provider_preference(tmp_path, monkeypatch):
    # unset any existing environment variables
    monkeypatch.delenv("NEXTGEN_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("FOUNDRY_MODEL_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DEPLOYMENT_NAME", raising=False)

    # case: only foundry model name set -> provider becomes foundry
    monkeypatch.setenv("FOUNDRY_MODEL_NAME", "gpt-4.1-test")
    # re-initialize config instance
    cfg = config  # global instance
    # force reload of attributes by re-running __init__
    cfg.__init__()
    assert cfg.model_provider == "foundry"
    assert cfg.validate()
    assert cfg.foundry_model_name == "gpt-4.1-test"

    # case: explicit provider override to azure should favour azure
    monkeypatch.setenv("NEXTGEN_MODEL_PROVIDER", "azure")
    cfg.__init__()
    assert cfg.model_provider == "azure"
    # azure validation will fail without endpoint/dep
    assert not cfg.validate()

    # case: foundry endpoint also present but provider explicitly azure
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.cognitiveservices.azure.com/")
    cfg.__init__()
    assert cfg.model_provider == "azure"  # override respected

    # case: explicit provider foundry with minimal settings
    monkeypatch.setenv("NEXTGEN_MODEL_PROVIDER", "foundry")
    monkeypatch.delenv("FOUNDRY_MODEL_NAME", raising=False)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.cognitiveservices.azure.com/")
    cfg.__init__()
    assert cfg.model_provider == "foundry"
    # validate now fails because model name missing
    assert not cfg.validate()

