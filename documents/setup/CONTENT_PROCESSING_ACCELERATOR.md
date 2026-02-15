# Content Processing Accelerator Integration

This project can use the Microsoft Content Processing Solution Accelerator to improve extraction quality for PDFs, Word files, and scanned documents. The accelerator runs a multi-service pipeline (Document Intelligence, Search, Storage, OpenAI) and exposes an API that Belle can call for richer structured outputs.

## Deploy in Azure (West US 3)

Use the accelerator repo deployment guidance and target your existing resource group in West US 3.

High-level steps:

1. Clone the accelerator repo and follow its deployment instructions.
2. Choose West US 3 for all resources.
3. Use the same resource group as this project.
4. Record the API endpoint and API key for the content processing service.
5. Store the endpoint and key in Azure Key Vault or .env.local.

## Required Secrets

Store these in Azure Key Vault (recommended) or .env.local for local development:

- `content-processing-endpoint`
- `content-processing-api-key`
- `content-processing-api-key-header` (default: `x-api-key`)
- `content-processing-enabled` (set to `true`)

## Expected API Contract

Belle calls the endpoint with a JSON payload that includes the file name and text. The service can return raw extraction results and any normalized fields:

Request:

```json
{
  "file_name": "student_application.pdf",
  "text": "...extracted text...",
  "include_raw": true
}
```

Response (example shape):

```json
{
  "document_type": "application",
  "confidence": 0.86,
  "summary": "...",
  "text": "...normalized text...",
  "student_info": {
    "name": "Ava Carter",
    "email": "ava@example.com",
    "school_name": "Lincoln High School"
  },
  "extracted_data": {
    "gpa": 3.9,
    "ap_courses": ["AP Biology", "AP Calculus"],
    "activities": ["Robotics", "Debate"],
    "interest": "Biomedical Engineering"
  },
  "raw": {
    "layout": {"...": "..."}
  }
}
```

Belle merges any returned fields into `agent_fields` and stores the full response as `raw_extraction` for downstream use.

## Validation

1. Upload a document.
2. Confirm the UI shows Belle as working.
3. Verify `raw_extraction` is present in the Belle output (debug logs or saved output).
