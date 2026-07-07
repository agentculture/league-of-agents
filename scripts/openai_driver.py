#!/usr/bin/env python3
"""Harness driver for any OpenAI-compatible endpoint (e.g. the colleague vLLM).

Reads the seat/commander prompt on stdin, POSTs one chat completion, prints
the model's reply (with any <think>…</think> blocks stripped so a draft JSON
inside the model's reasoning can't be mistaken for its answer). stdlib only.

Usage (as a harness command driver):

    {"type": "command", "per_seat": true,
     "argv": ["python3", "scripts/openai_driver.py",
              "--model", "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"]}

Environment: COLLEAGUE_BASE_URL overrides the default http://localhost:8001/v1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("COLLEAGUE_BASE_URL", "http://localhost:8001/v1"),
    )
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.6)
    args = parser.parse_args()

    prompt = sys.stdin.read()
    body = json.dumps(
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.base_url}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=280) as response:  # nosec B310
        payload = json.load(response)
    message = payload["choices"][0]["message"]
    # Thinking models may put the answer in content and reasoning in
    # reasoning_content — or leave content null when the budget ran dry.
    content = message.get("content") or message.get("reasoning_content") or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)
    print(content.strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # top-level guard: no raw traceback, stdout stays result-only
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
