"""OE_DEEPSEEK_URL: the operator can point DeepSeek calls at another endpoint.

The endpoint table is built when ai_client is imported, so each case imports
it in a fresh interpreter with its own environment instead of reloading the
module inside this process (other modules hold references to its objects).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

PROBE = "from app.modules.ai import ai_client; print(ai_client._openai_compat_endpoint('deepseek'))"


def _endpoint(value: str | None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "OE_DEEPSEEK_URL"}
    if value is not None:
        env["OE_DEEPSEEK_URL"] = value
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_default_is_the_public_deepseek_api() -> None:
    assert _endpoint(None) == "https://api.deepseek.com/chat/completions"


def test_blank_value_keeps_the_default() -> None:
    assert _endpoint("") == "https://api.deepseek.com/chat/completions"


def test_operator_override_is_used() -> None:
    assert _endpoint("http://fake-ai:8000/chat/completions") == "http://fake-ai:8000/chat/completions"
