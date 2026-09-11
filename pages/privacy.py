"""Privacy page ("/privacy"). Split out of app.py as part of the
app.py-modularization pass -- see docs/DESIGN.md's "Codebase structure"
section."""

from __future__ import annotations

import html
import re

from pages import FOOTER_HTML
from profiles_store import PROJECT_DIR


def render_markdown_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)


def render_privacy_markdown(text: str) -> str:
    """Minimal markdown -> HTML for PRIVACY.md's own subset (#, ##, bold, - and 1. lists,
    plain paragraphs). Not a general-purpose renderer -- deliberately narrow so this page
    stays dependency-free; a simple render step is enough for PRIVACY.md's own limited
    markdown subset. A top-level '# ' heading renders as h2 and '## ' as h3, one level below this page's own
    <h1>Privacy</h1>, so the document's own title doesn't produce a second <h1>."""
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    def flush_paragraph() -> None:
        if paragraph_lines:
            blocks.append(f"<p>{render_markdown_inline(' '.join(paragraph_lines))}</p>")
            paragraph_lines.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items and list_tag:
            items_html = "".join(f"<li>{render_markdown_inline(item)}</li>" for item in list_items)
            blocks.append(f"<{list_tag}>{items_html}</{list_tag}>")
            list_items.clear()
        list_tag = None

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h2>{render_markdown_inline(line[2:])}</h2>")
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h3>{render_markdown_inline(line[3:])}</h3>")
            continue
        bullet_match = re.match(r"^- (.+)$", line)
        numbered_match = re.match(r"^\d+\. (.+)$", line)
        if bullet_match:
            flush_paragraph()
            if list_tag != "ul":
                flush_list()
                list_tag = "ul"
            list_items.append(bullet_match.group(1))
            continue
        if numbered_match:
            flush_paragraph()
            if list_tag != "ol":
                flush_list()
                list_tag = "ol"
            list_items.append(numbered_match.group(1))
            continue
        flush_list()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def privacy_page() -> str:
    privacy_text_en = (PROJECT_DIR / "PRIVACY.md").read_text(encoding="utf-8")
    privacy_text_it = (PROJECT_DIR / "PRIVACY.it.md").read_text(encoding="utf-8")
    content_html_en = render_privacy_markdown(privacy_text_en)
    content_html_it = render_privacy_markdown(privacy_text_it)

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Privacy</title>
  <script src="/static/i18n.js" defer></script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/privacy.css">
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <h1 class="sr-only">Privacy</h1>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="header-right">
        <a class="nav-link nav-secondary" href="/getting-started">Getting Started</a>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
  </header>
  <section class="panel">
    <div data-lang-block="en">
    {content_html_en}
    </div>
    <div data-lang-block="it" hidden>
    {content_html_it}
    </div>
  </section>
  {FOOTER_HTML}
</main>
</body>
</html>"""
