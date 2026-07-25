# Azure Model Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Azure Blob Storage-backed model caching so large single-file model weights stay out of the repo/installer and can be restored on demand.

**Architecture:** Keep Studio's existing Model Manager as the install entrypoint. Add an optional Azure Blob cache layer that checks remote storage before downloading from Hugging Face/Civitai and uploads newly downloaded single-file artifacts back to Azure when enabled.

**Tech Stack:** Python FastAPI backend, Azure Blob Storage optional dependency, PowerShell Azure CLI setup script, React Cloud page.

---

### Task 1: Backend Cache Behavior

**Files:**
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/services/model_manager.py`
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/integrations/azure.py`
- Test: `tests/test_azure_model_cache.py`

- [ ] Write failing tests for cache hit and cache upload behavior around single-file model installs.
- [ ] Run `python -m pytest tests/test_azure_model_cache.py -q` and confirm the missing cache API fails.
- [ ] Add the Azure cache adapter and wire it into `ModelManager._install_file_model`.
- [ ] Re-run the focused pytest command and confirm it passes.

### Task 2: Cloud Page Azure Test

**Files:**
- Modify: `studio/edmg-studio/src/pages/Cloud.tsx`
- Modify: `studio/edmg-studio/src/test/Cloud.test.tsx`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/app.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/schemas.py`

- [ ] Add a failing Vitest assertion for `/v1/cloud/azure/test`.
- [ ] Add backend schema and route for testing Azure Blob credentials/container access.
- [ ] Add an Azure panel to the Cloud page.
- [ ] Run the focused Vitest command and confirm it passes.

### Task 3: CLI Setup and Docs

**Files:**
- Create: `deployment/azure/setup_model_cache.ps1`
- Create: `docs/AZURE_MODEL_CACHE.md`
- Modify: `.env.template`
- Modify: `studio/edmg-studio/python_backend/pyproject.toml`

- [ ] Add Azure optional dependencies.
- [ ] Add env var examples for enabling the model cache.
- [ ] Add an Azure CLI script that logs in if needed, creates/reuses a resource group, storage account, container, and prints env vars.
- [ ] Document that large model weights belong in Blob Storage, not SQL/Cosmos databases; databases are for metadata if a future multi-user backend needs them.

### Task 4: Verification

**Files:**
- No new files.

- [ ] Run backend focused tests.
- [ ] Run Cloud page focused UI tests.
- [ ] Report that `az` is not installed in this local shell, so live login/provisioning was not executed here.
