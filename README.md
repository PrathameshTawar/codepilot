# 🚀 CodePilot — Autonomous Coding Agent with Secure Sandbox & Self-Correction

> **Production-grade AI Software Engineer** that analyzes codebases, plans repairs, safely executes tests in an isolated sandbox, diagnoses failure tracebacks, and executes bounded self-correction loops with human review gating.

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/Tests-29%20Passed-brightgreen.svg)](#evaluation--benchmarks)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

---

## 🎯 The Problem CodePilot Solves
Ordinary AI code generators output raw snippets without verifying whether they compile or pass tests. When code breaks, users are left copying tracebacks manually back and forth.

**CodePilot implements a complete closed-loop engineering workflow:**
```
Task / Issue ➡️ Repository Inspection ➡️ Baseline Test Run ➡️ Diagnostic Extraction
      ⬆️                                                                 ⬇️
Review & Approval ⬅️ Final Verification ⬅️ Atomic Patch Application ⬅️ Bounded Repair Plan
```

---

## 🏗️ Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       FastAPI API Layer                     │
│           (Task Dispatch, Status Polling, Review Gate)      │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                    CodePilotAgent Controller                │
│    (State Machine, Task Lifecycle, Bounded Retry Budget)    │
└──────┬───────────────────────┬──────────────────────────────┘
       │                       │
┌──────▼─────────────┐  ┌──────▼─────────────┐  ┌─────────────▼────────┐
│  RepositoryReader  │  │    PatchEngine     │  │    SandboxRunner     │
│  - Path Traversal  │  │  - AST Validation  │  │  - Timeout Guard     │
│  - File Discovery  │  │  - Unified Diff    │  │  - Command Allowlist │
│  - Safe Slicing    │  │  - Atomic Rollback │  │  - Subprocess Contain│
└────────────────────┘  └────────────────────┘  └─────────────┬────────┘
                                                              │
                                                ┌─────────────▼────────┐
                                                │   DiagnosticEngine   │
                                                │  - Pytest Extractor  │
                                                │  - Error Signatures  │
                                                │  - Context Limiter   │
                                                └──────────────────────┘
```

---

## 🛡️ Security & Containment Architecture

1. **Path Traversal Prevention:** `RepositoryReader` strictly resolves and checks that all file accesses stay within the repository root boundary. Directory traversal attacks (`../../`) are blocked with `PermissionError`.
2. **Forbidden Command Guard:** Destructive shell patterns (`rm -rf`, `format`, `del /s`, `curl`, `wget`, `powershell -enc`, etc.) are actively intercepted by `SandboxRunner`.
3. **Execution Timeout Containment:** Subprocess execution enforces strict timeouts (default 30s) to prevent infinite loops, hanging scripts, or fork bombs.
4. **AST Pre-Validation:** `PatchEngine` validates Python syntax trees with `ast.parse` *before* touching disk. Syntax-broken patches are rejected without corrupting the codebase.
5. **Human Review Gate:** Merging or applying final fixes requires human approval through `/tasks/{task_id}/approve`.

---

## 🚀 Quickstart Guide

### 1. Clone & Set Up
```powershell
git clone https://github.com/PrathameshTawar/codepilot.git
cd codepilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run Test Suite
```powershell
python -m pytest -v
```
All **29 unit and integration tests** execute in seconds with zero external network dependencies.

### 3. Start the FastAPI Server
```powershell
uvicorn app.api.main:app --reload --port 8000
```
Open interactive Swagger UI docs at: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📡 REST API Reference

### Health Check
`GET /health`
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2026-10-20T14:30:00Z"
}
```

### Submit Coding Task
`POST /tasks`
```json
{
  "description": "Fix discount percentage calculation and add validation",
  "repo_path": "path/to/project",
  "test_command": "pytest",
  "max_attempts": 3
}
```

### Human Review Approval Gate
`POST /tasks/{task_id}/approve`
```json
{
  "approved": true,
  "reviewer": "Alice",
  "comments": "Verified clean patch and tests pass."
}
```

---

## 📊 Evaluation & Benchmarks

| Metric | Measured Result | Significance |
| :--- | :--- | :--- |
| **Test Pass Rate** | **100% (29/29 tests passed)** | Full coverage across sandbox, AST validation, and agent loop |
| **Path Traversal Defense** | **100% Block Rate** | Directory escape attempts blocked deterministically |
| **Self-Correction Success** | **Verified** | Repaired failing discount percentage bug in 1 attempt |
| **Execution Cost** | **₹0 / Free** | Completely runnable on local CPU without paid API dependencies |

---

## 🗺️ Roadmap
- [x] Milestone 1: Deterministic Bounded Retry Engine (`RetryBudget`)
- [x] Milestone 2: Traversal-safe Repository Inspector (`RepositoryReader`)
- [x] Milestone 3: AST-validating Patch Engine with Rollback (`PatchEngine`)
- [x] Milestone 4: Isolated Sandbox Process Runner (`SandboxRunner`)
- [x] Milestone 5: Error Diagnosis and Closed-Loop Controller (`CodePilotAgent`)
- [x] Milestone 6: REST API with Human Review Gate (`FastAPI`)
- [ ] Milestone 7: Optional Docker container isolation backend
- [ ] Milestone 8: GitHub Issues webhook listener and PR auto-creation

---

## 📄 License
MIT License. Built for Production AI Engineering & Agentic Systems.
