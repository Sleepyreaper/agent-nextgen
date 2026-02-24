Foundry Model Integration (gpt-4.1)
=====================================

Summary
-------
This project now supports calling a Foundry-hosted model deployment (example: `gpt-4.1`). Agents will default to the Foundry model when `NEXTGEN_MODEL_PROVIDER=foundry` or when `config.foundry_project_endpoint` is present.

Required configuration (provide these from Foundry)
-------------------------------------------------
- `FOUNDRY_PROJECT_ENDPOINT` (or `foundry-project-endpoint` in Key Vault)
  - Base URL for the Foundry inference service. Historically this was a
    `*.services.ai.azure.com/api/projects/...` URL; the client will automatically
    translate such values to the equivalent
    `*.cognitiveservices.azure.com` host when making chat completion calls.
    You may also supply the plain Cognitive Services/OpenAI endpoint directly.
    Example values (project root or plain host only):

      * `https://nextgenagentfoundry.services.ai.azure.com/api/projects/nextgenagents`
      * `https://nextgenagentfoundry.cognitiveservices.azure.com`
      * `https://foundry.example.net/api/v1`

    Do **not** include application-specific or protocol paths (e.g.
    `/applications/foo/...`).  Those paths are ignored when the client
    builds chat-completion URLs and will lead to incorrect requests.- `FOUNDRY_API_KEY` (or `foundry-api-key` in Key Vault)
  - Bearer token or API key for service-to-service authentication.
- `FOUNDRY_MODEL_NAME` (or `foundry-model-name` in Key Vault)
  - The model id/deployment name to call (e.g. `gpt-4.1`).
- `NEXTGEN_MODEL_PROVIDER=foundry`
  - Optional environment hint (if omitted and `FOUNDRY_PROJECT_ENDPOINT` exists, provider defaults to `foundry`).

Optional but useful
-------------------
- `FOUNDRY_PROJECT_NAME` / `foundry-project-name` — project or deployment identifier if Foundry requires it.
- Timeout / rate limit guidance — share any per-minute QPS or burst limits so agents can back off.

Request shape expected by this code
----------------------------------
The included `FoundryClient` adapter posts JSON to `${FOUNDRY_PROJECT_ENDPOINT}/generate` with:

{
  "model": "<FOUNDRY_MODEL_NAME>",
  "input": "<concatenated messages: [role] content...>",
  "temperature": 0.7,
  "max_completion_tokens": 1200
}

Response handling
-----------------
The adapter tries to extract text from common response shapes: `output`, `outputs[]`, `choices[]`, or falls back to JSON-stringifying the body. It returns an object with `choices[0].message.content` to be compatible with the existing agent code.

If your Foundry model uses a different endpoint or request/response schema, supply the canonical endpoint and an example request/response payload and I will update `FoundryClient` to match exactly.

Security
--------
- Store `FOUNDRY_API_KEY` in Key Vault or environment variables (use the project's Key Vault integration). Do not commit it to source control.

Next steps for verification
---------------------------
1. Provide the concrete `FOUNDRY_PROJECT_ENDPOINT` (full URL) and `FOUNDRY_MODEL_NAME`.
2. Provide a sample curl request + response (if available) from Foundry so the adapter can be tightened to the exact API shape.
3. I will deploy a small E2E smoke test to call the model and confirm output mapping.
