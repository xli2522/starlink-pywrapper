from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile


GENERATOR = (
    Path(__file__).resolve().parents[2] / "helperscripts" / "generate_functions.py"
)
SPEC = importlib.util.spec_from_file_location("signature_override_generator", GENERATOR)
assert SPEC and SPEC.loader
generate_functions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_functions)


def test_signature_override_preserves_existing_python_call_shape():
    parameter = generate_functions.parinfo(
        "newrequired",
        "_CHAR",
        "prompt",
        None,
        "1",
        None,
        None,
        "READ",
        None,
        None,
        None,
        False,
        "read",
    )
    info = generate_functions.commandinfo(
        "legacy", "Description", {"newrequired": parameter}, None
    )
    docs = generate_functions.make_docstrings({"legacy": info})

    with tempfile.TemporaryDirectory() as temp:
        previous = os.getcwd()
        os.chdir(temp)
        try:
            generate_functions.create_module(
                "KAPPA",
                ["legacy"],
                docs,
                {"legacy": "$KAPPA_DIR/legacy"},
                {"legacy": info},
                signature_overrides={"legacy": "*args, **kwargs"},
            )
            generated = Path("kappa.py").read_text(encoding="utf-8")
        finally:
            os.chdir(previous)

    assert "def legacy(*args, **kwargs):" in generated
    assert "('newrequired', '_CHAR', False, 'READ')" in generated
