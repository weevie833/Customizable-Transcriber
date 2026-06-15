from __future__ import annotations

import cgi
import html
import re
import threading
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from xml.etree import ElementTree

from transcription_bot.core import (
    DEFAULT_MODEL,
    TranscriptionConfig,
    count_failures,
    default_output_file,
    run_batch,
)


PROJECT_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
SOURCE_FOLDER = Path("/Users/stevecovello/Desktop/MM/Transcription Sources")
TOOLS = {
    "morti": {
        "label": "Morti",
        "prompt": PROJECT_DIR / "prompts" / "morti.md",
    },
    "battisme": {
        "label": "Battisme",
        "prompt": PROJECT_DIR / "prompts" / "battesimi.md",
    },
    "matrimoni": {
        "label": "Matrimoni",
        "prompt": PROJECT_DIR / "prompts" / "matrimoni.md",
    },
    "generic": {
        "label": "Generic",
        "prompt": PROJECT_DIR / "prompts" / "generic.md",
    },
}

state = {
    "running": False,
    "log": [],
    "output": "",
    "download": "",
    "summary": "",
}
lock = threading.Lock()


def add_log(message: str) -> None:
    with lock:
        state["log"].append(message)
        state["log"] = state["log"][-300:]


def safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    clean = clean.strip(".-")
    return clean or "transcription-output.md"


def output_stem() -> str:
    return default_output_file(PROJECT_DIR).stem


def selected_tool(form: cgi.FieldStorage) -> str:
    tool = form.getfirst("tool", "")
    if tool not in TOOLS:
        raise RuntimeError("Select Morti, Battisme, Matrimoni, or Generic before running transcription.")
    return tool


def destination_output_file(tool: str) -> Path:
    return PROJECT_DIR / "outputs" / f"{tool}-{output_stem()}.docx"


def page() -> str:
    with lock:
        running = bool(state["running"])
        log = "\n".join(state["log"])
        output = str(state["output"])
        download = str(state["download"])
        summary = str(state["summary"])

    disabled = "disabled" if running else ""
    escaped_log = html.escape(log)
    escaped_output = html.escape(output)
    escaped_summary = html.escape(summary)
    download_link = (
        f'<a class="download" href="/download" download>Download Document</a>'
        if download
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Transcription Bot</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    body {{
      margin: 0;
      background: #f7f5f0;
      color: #1f2933;
    }}
    main {{
      max-width: 900px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1 {{
      margin: 0 0 20px;
      font-size: 28px;
    }}
    form, .panel {{
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    label {{
      display: block;
      font-weight: 650;
      margin-top: 14px;
    }}
    input[type="text"], input[type="number"] {{
      box-sizing: border-box;
      width: 100%;
      margin-top: 6px;
      padding: 10px 12px;
      border: 1px solid #b8b2a5;
      border-radius: 6px;
      font: inherit;
      background: #fff;
      color: #1f2933;
    }}
    .path-control {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }}
    .path-display {{
      min-height: 22px;
      margin-top: 6px;
      overflow-wrap: anywhere;
      color: #4b5563;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
    }}
    input[type="file"] {{
      display: none;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .tool-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .tool-grid input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .tool-grid span {{
      display: block;
      padding: 10px 12px;
      border: 1px solid #8d99a6;
      border-radius: 6px;
      text-align: center;
      font-weight: 700;
      cursor: pointer;
      background: #fff;
    }}
    .tool-grid input:checked + span {{
      border-color: #255c99;
      background: #255c99;
      color: #fff;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 14px;
      font-weight: 500;
    }}
    .check input {{
      appearance: none;
      width: 16px;
      height: 16px;
      margin: 0;
      border: 1.5px solid #4b5563;
      border-radius: 2px;
      background: transparent;
    }}
    .check input:checked {{
      background: #255c99;
      border-color: #255c99;
      box-shadow: inset 0 0 0 3px #fff;
    }}
    button {{
      margin-top: 18px;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #255c99;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .button-label, .download {{
      display: inline-block;
      margin-top: 0;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #53616f;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
    }}
    .path-control button {{
      margin-top: 0;
      white-space: nowrap;
      background: #53616f;
    }}
    button:disabled {{
      background: #8d99a6;
      cursor: wait;
    }}
    pre {{
      min-height: 220px;
      overflow: auto;
      white-space: pre-wrap;
      background: #15191f;
      color: #e8edf2;
      border-radius: 8px;
      padding: 14px;
    }}
    .summary {{
      color: #37546b;
      font-weight: 650;
    }}
    @media (max-width: 720px) {{
      .row, .tool-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>Transcription Bot</h1>
  <form method="post" action="/run">
    <label>Transcription tool</label>
    <div class="tool-grid">
      <label><input type="radio" name="tool" value="morti" required><span>Morti</span></label>
      <label><input type="radio" name="tool" value="battisme" required><span>Battisme</span></label>
      <label><input type="radio" name="tool" value="matrimoni" required><span>Matrimoni</span></label>
      <label><input type="radio" name="tool" value="generic" required><span>Generic</span></label>
    </div>
    <div class="path-control">
      <label>Source folder
        <div class="path-display">{html.escape(str(SOURCE_FOLDER))}</div>
      </label>
    </div>
    <div class="row">
      <label>Gemini model
        <input type="text" name="model" value="{DEFAULT_MODEL}">
      </label>
      <label>Delay between images
        <input type="number" name="delay" value="2" min="0" step="0.5">
      </label>
    </div>
    <label class="check">
      <input type="checkbox" name="reverse"> Process in reverse chronological order
    </label>
    <button type="submit" {disabled}>Run transcription</button>
  </form>
  <section class="panel">
    <div class="summary">{escaped_summary}</div>
    <p>Output: {escaped_output}</p>
    <p><a href="/">Refresh Status</a></p>
    {download_link}
    <pre>{escaped_log}</pre>
  </section>
</main>
</body>
</html>"""


def paragraph(text: str) -> ElementTree.Element:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = ElementTree.Element(f"{{{ns}}}p")
    r = ElementTree.SubElement(p, f"{{{ns}}}r")
    t = ElementTree.SubElement(r, f"{{{ns}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return p


def content_types_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def root_rels_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def document_xml(text: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ElementTree.register_namespace("w", ns)
    document = ElementTree.Element(f"{{{ns}}}document")
    body = ElementTree.SubElement(document, f"{{{ns}}}body")
    for line in text.splitlines():
        body.append(paragraph(line))
    sect_pr = ElementTree.SubElement(body, f"{{{ns}}}sectPr")
    pg_sz = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgSz")
    pg_sz.set(f"{{{ns}}}w", "12240")
    pg_sz.set(f"{{{ns}}}h", "15840")
    pg_mar = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgMar")
    pg_mar.set(f"{{{ns}}}top", "1440")
    pg_mar.set(f"{{{ns}}}right", "1440")
    pg_mar.set(f"{{{ns}}}bottom", "1440")
    pg_mar.set(f"{{{ns}}}left", "1440")
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def write_docx(output_docx: Path, text: str) -> None:
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("[Content_Types].xml", content_types_xml())
        output.writestr("_rels/.rels", root_rels_xml())
        output.writestr("word/document.xml", document_xml(text))


def run_job(form: cgi.FieldStorage, output_file: Path, tool: str) -> None:
    try:
        image_folder = SOURCE_FOLDER
        markdown_file = PROJECT_DIR / "outputs" / f"{output_file.stem}.md"
        delay = float(form.getfirst("delay", "2") or "2")
        prompt_file = TOOLS[tool]["prompt"]
        if not prompt_file.exists():
            raise RuntimeError(f"Prompt file is missing for {TOOLS[tool]['label']}: {prompt_file}")

        config = TranscriptionConfig(
            image_folder=image_folder,
            output_file=markdown_file,
            prompt_file=prompt_file,
            model=form.getfirst("model", DEFAULT_MODEL) or DEFAULT_MODEL,
            delay_seconds=delay,
            reverse_order="reverse" in form.keys(),
        )
        results = run_batch(config, PROJECT_DIR, progress=add_log)
        write_docx(output_file, markdown_file.read_text(encoding="utf-8"))
        failures = count_failures(results)
        with lock:
            state["summary"] = f"Processed {len(results)} image(s), {failures} failure(s)."
            state["download"] = str(output_file)
    except Exception as exc:
        add_log(f"Fatal error: {exc}")
        with lock:
            state["summary"] = f"Fatal error: {exc}"
    finally:
        with lock:
            state["running"] = False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/download":
            self.download()
            return

        if parsed.path != "/":
            self.redirect_home()
            return

        self.respond(page())

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(404)
            return

        with lock:
            if state["running"]:
                self.respond(page())
                return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )

        try:
            tool = selected_tool(form)
        except Exception as exc:
            with lock:
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.respond(page())
            return

        output_file = destination_output_file(tool)
        with lock:
            state["running"] = True
            state["log"] = []
            state["output"] = str(output_file)
            state["download"] = ""
            state["summary"] = f"Running {TOOLS[tool]['label']}..."

        thread = threading.Thread(target=run_job, args=(form, output_file, tool), daemon=True)
        thread.start()
        self.respond(page())

    def download(self) -> None:
        with lock:
            download = str(state["download"])
        if not download:
            self.send_error(404)
            return
        path = Path(download)
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        if path.suffix.lower() == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            content_type = "text/markdown; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Transcription Bot running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
