"""Modal App + Image definition. See SPEC.md §8.1.

Dependencies are baked into the image at build time — nothing is
`pip install`ed at sandbox-creation time. There is no `write_report`
dependency here: report emission is a client-side tool (§9.4), handled
entirely in workflow code.

`app` and `image` are built lazily (on first attribute access, via
`__getattr__`, PEP 562) rather than at module import time. Functionally this
is `app = modal.App.lookup(...)` at import — but computing it eagerly would
make *importing this module* perform a real Modal network call, which would
fire during test collection even when `modal` is mocked only inside a test
function. Lazy construction means `import sbda.sandboxes.modal_image` is
always side-effect-free; the network call only happens the first time
`sandbox.py`'s activities actually touch `.app` / `.image`, at which point
tests have already patched `modal`.
"""

from __future__ import annotations

from functools import lru_cache

import modal

APP_NAME = "sbda-sandboxes"


@lru_cache(maxsize=1)
def get_app() -> "modal.App":
    return modal.App.lookup(APP_NAME, create_if_missing=True)


@lru_cache(maxsize=1)
def get_image() -> "modal.Image":
    return modal.Image.debian_slim(python_version="3.12").pip_install(
        "pandas==2.2.*",
        "numpy==2.*",
        "openpyxl==3.1.*",
        "xlrd==2.0.*",
        "pyarrow==18.*",
        "chardet==5.*",
    )


def __getattr__(name: str):
    if name == "app":
        return get_app()
    if name == "image":
        return get_image()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
