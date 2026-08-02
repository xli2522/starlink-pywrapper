from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import warnings


GENERATOR = (
    Path(__file__).resolve().parents[2] / "helperscripts" / "generate_functions.py"
)
SPEC = importlib.util.spec_from_file_location("escape_generator", GENERATOR)
assert SPEC and SPEC.loader
generate_functions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_functions)


def test_generated_backslashes_do_not_raise_invalid_escape_warnings():
    info = generate_functions.commandinfo(
        "alias", r"Uses a literal \* pattern.", {}, None
    )
    docs = generate_functions.make_docstrings({"alias": info})
    with tempfile.TemporaryDirectory() as temp:
        previous = os.getcwd()
        os.chdir(temp)
        try:
            generate_functions.create_module(
                "KAPPA",
                ["alias"],
                docs,
                {"alias": r"${KAPPA_DIR}/fitsmod position=\!"},
                {"alias": info},
            )
            source = Path("kappa.py").read_text(encoding="utf-8")
        finally:
            os.chdir(previous)

    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, "kappa.py", "exec")
