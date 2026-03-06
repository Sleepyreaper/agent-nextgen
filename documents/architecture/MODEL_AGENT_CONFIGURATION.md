# Model & Agent Configuration

**Last Updated**: June 2025  
**Status**: ✅ 4-tier model architecture deployed (v1.0.39)

---

## 🚀 4-Tier Model Architecture

The system uses five model tiers configured via Azure Key Vault or environment variables:

| Tier | Config Key | Default Deployment | Purpose |
|------|-----------|-------------------|---------|
| **Premium** | `model_tier_premium` | `gpt-4.1` | Deep reasoning tasks |
| **Merlin** | `model_tier_merlin` | `MerlinGPT5Mini` | Final evaluation (dedicated) |
| **Workhorse** | `model_tier_workhorse` | `WorkForce4.1mini` | General agent tasks |
| **Lightweight** | `model_tier_lightweight` | `LightWork5Nano` | High-volume simple tasks |
| **Vision** | `foundry_vision_model_name` | `gpt-4o` | Multimodal (video, OCR) |

---

## 🎭 Agent → Model Tier Mapping

### Premium Tier (`gpt-4.1`)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Rapunzel | `RapunzelGradeReader` | Complex transcript reasoning |
| Milo | `MiloDataScientist` | ML code generation & statistical analysis |

### Merlin Tier (`MerlinGPT5Mini`)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Merlin | `MerlinStudentEvaluator` | Dedicated scaling for final eval |

### Workhorse Tier (`WorkForce4.1mini`)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Tiana | `TianaApplicationReader` | Structured data extraction |
| Mulan | `MulanRecommendationReader` | Letter analysis |
| Moana | `MoanaSchoolContext` | School profile enrichment |
| Gaston | `GastonEvaluator` | Counter-evaluation |
| Ariel | `ArielQAAgent` | Conversational Q&A (30s target) |
| Naveen | `NaveenSchoolDataScientist` | School data aggregation |
| Bashful | `BashfulAgent` | Output summarization |

### Lightweight Tier (`LightWork5Nano`)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Belle | `BelleDocumentAnalyzer` | High-volume document classification |
| FeedbackTriage | `FeedbackTriageAgent` | Fast feedback categorization |

### Vision Tier (`gpt-4o`)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Mirabel | `MirabelVideoAnalyzer` | Video frame analysis |
| Belle (OCR) | `BelleDocumentAnalyzer` | Scanned page OCR fallback |

### Local / Programmatic (no model)
| Agent | Class | Rationale |
|-------|-------|-----------|
| Aurora | `AuroraAgent` | Formatting only |
| Fairy Godmother | `FairyGodmotherDocumentGenerator` | Template-based generation |

---

## 🔧 Configuration in `src/config.py`

```python
# Key Vault secrets (with env var fallbacks)
self.model_tier_premium = self._get_secret("model-tier-premium", "MODEL_TIER_PREMIUM") or "gpt-4.1"
self.model_tier_merlin = self._get_secret("model-tier-merlin", "MODEL_TIER_MERLIN") or "MerlinGPT5Mini"
self.model_tier_workhorse = self._get_secret("model-tier-workhorse", "MODEL_TIER_WORKHORSE") or "WorkForce4.1mini"
self.model_tier_lightweight = self._get_secret("model-tier-lightweight", "MODEL_TIER_LIGHTWEIGHT") or "LightWork5Nano"
self.foundry_vision_model_name = self._get_secret("foundry-vision-model-name", "FOUNDRY_VISION_MODEL_NAME") or "gpt-4o"
```

### Agent Model Selection Pattern

Each agent uses a fallback chain:

```python
# Example from TianaApplicationReader
self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
```

This allows per-agent model override via constructor, with tier defaults from Key Vault, and legacy fallbacks.

---

## 📋 Model Metadata in Responses

All agents include model information in their output:

```json
{
  "agent_name": "Milo Data Scientist",
  "model_used": "gpt-4.1",
  "model_display": "gpt-4.1",
  "status": "success",
  ...
}
```

---

## 🔄 Changing Model Assignments

To change a model deployment for a tier:

1. Update the secret in Key Vault: `az keyvault secret set --vault-name nextgen-agents-kv --name model-tier-workhorse --value "new-deployment-name"`
2. Restart the app: `az webapp restart -g <your-resource-group> -n <your-webapp>`
3. All agents using that tier will automatically pick up the new deployment

To change a single agent's tier, edit its `__init__` method to reference a different `config.model_tier_*` property.
