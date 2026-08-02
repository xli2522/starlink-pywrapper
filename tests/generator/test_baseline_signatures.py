from __future__ import annotations

import json
from pathlib import Path
import tempfile

from helperscripts.metadata_2025a import baseline_signatures


def test_baseline_signature_loader_handles_reserved_python_names():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "manifests").mkdir()
        (root / "manifests" / "api_manifest_baseline.json").write_text(
            json.dumps(
                {
                    "modules": {
                        "demo": {
                            "public_callables": [
                                {
                                    "kind": "function",
                                    "name": "class_",
                                    "signature": "(in_, **kwargs)",
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        result = baseline_signatures(root, "demo")
    assert result == {"class": "in_, **kwargs"}
