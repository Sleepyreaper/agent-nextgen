#!/usr/bin/env python3
"""Preflight checks for runtime dependencies and configuration."""

import importlib
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_MODULES = [
    "openai",
    "azure.identity",
    "azure.keyvault.secrets",
    "flask",
    "werkzeug",
    "psycopg",
    "PyPDF2",
    "docx",
    "requests",
    "aiohttp",
]

DEPLOYMENT_MODULES = [
    "gunicorn",
]

OPTIONAL_MODULES = [
    "azure.storage.blob",
    "azure.monitor.opentelemetry",
    "opentelemetry",
]


def _check_imports(modules: list[str]) -> list[str]:
    missing = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)
    return missing


def _check_env() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    kv_disabled = os.getenv("AZURE_KEY_VAULT_DISABLED") == "1"
    kv_name = os.getenv("AZURE_KEY_VAULT_NAME")

    use_env = kv_disabled or not kv_name
    if not kv_disabled and not kv_name:
        warnings.append("AZURE_KEY_VAULT_NAME not set; using environment variables")

    if use_env:
        if not os.getenv("AZURE_OPENAI_ENDPOINT"):
            errors.append("AZURE_OPENAI_ENDPOINT is missing")
        if not os.getenv("AZURE_DEPLOYMENT_NAME"):
            errors.append("AZURE_DEPLOYMENT_NAME is missing")

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            missing_db = [
                name
                for name in ["POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
                if not os.getenv(name)
            ]
            if missing_db:
                errors.append("Missing database settings: " + ", ".join(missing_db))

    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") and os.getenv("NEXTGEN_CAPTURE_PROMPTS"):
        warnings.append("Telemetry enabled; ensure opentelemetry packages are installed")

    return errors, warnings


def _check_uploads_folder() -> list[str]:
    errors = []
    uploads_path = PROJECT_ROOT / "uploads"
    try:
        uploads_path.mkdir(parents=True, exist_ok=True)
        test_file = uploads_path / ".preflight_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"Uploads folder not writable: {uploads_path} ({exc})")
    return errors


def main() -> int:
    print("\n" + "=" * 80)
    print("PREFLIGHT CHECK")
    print("=" * 80)

    errors: list[str] = []
    warnings: list[str] = []

    missing_required = _check_imports(REQUIRED_MODULES)
    if missing_required:
        errors.append("Missing required Python modules: " + ", ".join(missing_required))

    missing_deploy = _check_imports(DEPLOYMENT_MODULES)
    if missing_deploy:
        warnings.append("Missing deployment modules: " + ", ".join(missing_deploy))

    missing_optional = _check_imports(OPTIONAL_MODULES)
    if missing_optional:
        warnings.append("Optional modules not available: " + ", ".join(missing_optional))

    env_errors, env_warnings = _check_env()
    errors.extend(env_errors)
    warnings.extend(env_warnings)

    errors.extend(_check_uploads_folder())

    if errors:
        print("\nERRORS")
        for item in errors:
            print(f"  - {item}")

    if warnings:
        print("\nWARNINGS")
        for item in warnings:
            print(f"  - {item}")

    if not errors:
        print("\n✅ Preflight OK")

    print("\n" + "=" * 80 + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
