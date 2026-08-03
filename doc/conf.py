from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlink import __version__


project = "starlink-pywrapper"
author = "Starlink pywrapper contributors"
copyright = "2013-2026, Starlink pywrapper contributors"
version = __version__
release = __version__
needs_sphinx = "7"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]
autosummary_generate = True
napoleon_numpy_docstring = True
source_suffix = ".rst"
master_doc = "index"
language = "en"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
