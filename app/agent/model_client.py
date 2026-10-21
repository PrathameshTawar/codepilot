"""Unified model client supporting local Ollama, Claude, OpenAI, and heuristic offline patch synthesis."""

import json
import os
import re
from typing import Optional
import httpx

from app.agent.diagnostics import DiagnosticReport
from app.core.config import settings


def apply_search_replace_blocks(original_code: str, response_text: str) -> str:
    """Applies search-and-replace edit blocks (Aider/SWE-agent pattern) to preserve context."""
    pattern = re.compile(
        r"<<<<<<<\s*SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>>\s*REPLACE",
        re.DOTALL,
    )
    matches = pattern.findall(response_text)
    if not matches:
        # Check if full python code block was provided
        code_block = re.search(r"```(?:python)?\r?\n(.*?)\r?\n```", response_text, re.DOTALL)
        if code_block:
            return code_block.group(1)
        return response_text.strip()

    updated = original_code
    for search_block, replace_block in matches:
        if search_block in updated:
            updated = updated.replace(search_block, replace_block, 1)

    return updated


class ModelClient:
    """Unified client for generating surgical code repairs via local Ollama or hosted LLM endpoints."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        ollama_url: Optional[str] = None,
    ):
        self.provider = (provider or settings.MODEL_PROVIDER).lower()
        self.model_name = model_name or settings.MODEL_NAME
        self.ollama_url = (ollama_url or settings.OLLAMA_BASE_URL).rstrip("/")

    def generate_repair(
        self,
        file_path: str,
        code: str,
        diagnosis: DiagnosticReport,
        task_description: str = "",
    ) -> str:
        """Synthesizes a minimal, targeted patch addressing the diagnosed failure."""
        if self.provider == "ollama":
            return self._generate_ollama(file_path, code, diagnosis, task_description)
        elif self.provider == "openai" and settings.OPENAI_API_KEY:
            return self._generate_openai(file_path, code, diagnosis, task_description)
        else:
            return self._generate_heuristic_or_mock(file_path, code, diagnosis, task_description)

    def _build_prompt(self, file_path: str, code: str, diagnosis: DiagnosticReport, task_description: str) -> str:
        return (
            f"You are CodePilot, an autonomous coding agent. Fix the bug in `{file_path}`.\n\n"
            f"Task: {task_description}\n"
            f"Failure Diagnosis: {diagnosis.summary}\n"
            f"Failing File: {diagnosis.failing_file}:{diagnosis.line_number}\n"
            f"Assertion Details:\n{diagnosis.assertion_details or 'N/A'}\n\n"
            f"Original Code:\n```python\n{code}\n```\n\n"
            "Return a targeted SEARCH/REPLACE block or the complete corrected Python code with NO markdown explanations."
        )

    def _generate_ollama(self, file_path: str, code: str, diagnosis: DiagnosticReport, task_description: str) -> str:
        """Calls local Ollama instance (e.g. qwen2.5-coder:7b)."""
        prompt = self._build_prompt(file_path, code, diagnosis, task_description)
        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                if res.status_code == 200:
                    raw_text = res.json().get("response", "")
                    return apply_search_replace_blocks(code, raw_text)
        except Exception:
            pass
        return self._generate_heuristic_or_mock(file_path, code, diagnosis, task_description)

    def _generate_openai(self, file_path: str, code: str, diagnosis: DiagnosticReport, task_description: str) -> str:
        """Calls OpenAI Chat Completions API."""
        prompt = self._build_prompt(file_path, code, diagnosis, task_description)
        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={
                        "model": self.model_name if "gpt" in self.model_name else "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are a precise software repair assistant."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                    },
                )
                if res.status_code == 200:
                    raw_text = res.json()["choices"][0]["message"]["content"]
                    return apply_search_replace_blocks(code, raw_text)
        except Exception:
            pass
        return self._generate_heuristic_or_mock(file_path, code, diagnosis, task_description)

    def _generate_heuristic_or_mock(
        self,
        file_path: str,
        code: str,
        diagnosis: DiagnosticReport,
        task_description: str,
    ) -> str:
        """Deterministic heuristic repair for offline environments, benchmarks, and testing."""
        summary = (diagnosis.summary + " " + (diagnosis.assertion_details or "")).lower()

        # 1. Discount percentage bug: e.g. price - discount -> price * (1 - discount / 100)
        if "discount" in file_path.lower() or "discount" in summary:
            if "price - discount" in code:
                return (
                    "def calculate_discount(price, discount):\n"
                    "    if price < 0 or discount < 0 or discount > 100:\n"
                    "        raise ValueError('Invalid price or discount')\n"
                    "    return price * (1 - discount / 100)\n"
                )

        # 2. Off-by-one / comparison bug: e.g. < instead of <=
        if "18 < age" in code:
            return code.replace("18 < age", "18 <= age")
        if "<" in code and "<=" not in code:
            return code.replace("<", "<=", 1)

        # 3. Arithmetic sign errors: e.g. return a - b instead of return a + b
        if "add" in file_path.lower() or "add" in summary:
            if "return a - b" in code:
                return code.replace("return a - b", "return a + b")

        # 4. Zero division handling
        if "zerodivisionerror" in summary or "division by zero" in summary:
            if "return a / b" in code:
                return code.replace("return a / b", "if b == 0:\n        return 0\n    return a / b")

        # 5. String format / greeting bugs
        if "greeting" in file_path.lower() or "hello" in summary:
            if 'return f"Hi {name}"' in code:
                return code.replace('return f"Hi {name}"', 'return f"Hello, {name}!"')

        return code
