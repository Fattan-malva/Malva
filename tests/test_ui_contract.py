"""Contract tests between the Python bridge (app.py) and the pill page (malva/ui/html.py).

These tests read app.py with ast instead of importing it, so they run without
pywebview or a display.
"""
import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = (ROOT / "app.py").read_text(encoding="utf-8")
HTML_SRC = (ROOT / "malva" / "ui" / "html.py").read_text(encoding="utf-8")


def _page() -> str:
    from malva.ui.html import PILL_HTML
    return PILL_HTML


def _inline_script(page: str) -> str:
    m = re.search(r"<script>(.*?)</script>", page, re.S)
    assert m, "inline <script> block missing"
    return m.group(1)


def _api_methods() -> set[str]:
    tree = ast.parse(APP_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MalvaAPI":
            return {f.name for f in node.body
                    if isinstance(f, ast.FunctionDef) and not f.name.startswith("_")}
    raise AssertionError("MalvaAPI not found in app.py")


def test_inline_script_is_valid_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = _inline_script(_page())
    proc = subprocess.run([node, "--check", "-"], input=script,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


def test_every_python_to_js_call_has_a_window_function():
    page = _page()
    called = set(re.findall(r'_call\("(\w+)"', APP_SRC))
    assert called, "no _call sites found in app.py"
    defined = set(re.findall(r"window\.(\w+) = function", page))
    missing = sorted(called - defined)
    assert not missing, f"app.py calls window functions that the page does not define: {missing}"


def test_every_js_api_call_exists_on_malva_api():
    script = _inline_script(_page())
    used = set(re.findall(r"pywebview\.api\.(\w+)", script))
    # The method name is the first argument of call(...). It is either a literal
    # or a ternary of two literals, so only the first argument is read.
    for first in re.findall(r"\bcall\(([^,)]*)", script):
        used |= set(re.findall(r"^\s*'(\w+)'", first))
        used |= set(re.findall(r"[?:]\s*'(\w+)'", first))
    used.discard("")
    methods = _api_methods()
    missing = sorted(used - methods)
    assert not missing, f"page calls API methods MalvaAPI does not have: {missing}"


def test_no_template_literal_interpolation_in_page_script():
    """Dynamic text must go through esc() or textContent, never `${...}` in innerHTML."""
    script = _inline_script(_page())
    assert "${" not in script, "template interpolation found; use esc() or textContent"


def test_every_used_css_class_is_styled():
    page = _page()
    style = re.search(r"<style>(.*?)</style>", page, re.S)
    assert style, "style block missing"
    css = style.group(1)
    body = page[page.index("</style>"):]
    used = set()
    for attr in re.findall(r'class="([^"]+)"', body):
        used |= set(attr.split())
    used |= set(re.findall(r"classList\.(?:toggle|add|remove)\('([\w-]+)'", body + _inline_script(page)))
    # Classes added dynamically from innerHTML templates in the script.
    for name in re.findall(r"class=\\?\"([^\"\\]+)\\?\"", _inline_script(page)):
        used |= set(name.split())
    unstyled = sorted(c for c in used
                      if c and not re.search(r"\." + re.escape(c) + r"(?![\w-])", css))
    assert not unstyled, f"classes used in markup/script but not styled: {unstyled}"


def test_pywebviewready_bridge_is_wired():
    script = _inline_script(_page())
    assert "pywebviewready" in script
    assert "ui_ready" in script
