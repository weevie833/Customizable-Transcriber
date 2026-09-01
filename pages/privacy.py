"""Privacy page ("/privacy"). Split out of app.py as part of the
app.py-modularization pass -- see CLAUDE.md."""

from __future__ import annotations

import html
import re

from profiles_store import PROJECT_DIR


def render_markdown_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)


def render_privacy_markdown(text: str) -> str:
    """Minimal markdown -> HTML for PRIVACY.md's own subset (#, ##, bold, - and 1. lists,
    plain paragraphs). Not a general-purpose renderer -- deliberately narrow so this page
    stays dependency-free (see HANDOFF.md's note that a simple render step is enough).
    A top-level '# ' heading renders as h2 and '## ' as h3, one level below this page's own
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
  <style>
    .panel {{
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 24px 28px;
      margin-bottom: 18px;
    }}
    .panel h2 {{
      margin-top: 0;
      font-size: 21px;
    }}
    .panel h3 {{
      font-size: 17px;
      margin-top: 26px;
    }}
    .panel p {{
      margin: 12px 0;
    }}
    .panel ul, .panel ol {{
      margin: 12px 0;
      padding-left: 24px;
    }}
    .panel li {{
      margin: 6px 0;
    }}
    @media (max-width: 720px) {{
      .site-header {{ align-items: stretch; }}
    }}
  </style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <div class="site-heading">
      <h1>Privacy</h1>
      <div class="byline-row">
        <p class="byline">Created by Steve Covello, 2026</p>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
    <nav class="site-nav" aria-label="Primary navigation">
      <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
      <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
      <a class="nav-link" href="/transcribe">Transcribe</a>
      <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
      <a class="nav-link" href="/test-mode">Test Mode</a>
    </nav>
  </header>
  <section class="panel">
    <div data-lang-block="en">
    {content_html_en}
    </div>
    <div data-lang-block="it" hidden>
    {content_html_it}
    </div>
  </section>
  <footer class="license">Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). Free to use, modify, and share — derivative works, including hosted versions, must stay open source under the same license. &middot; <a href="/privacy">Privacy</a> <span id="app-version"></span></footer>
</main>
</body>
</html>"""
