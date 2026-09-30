"""Render Markdown design docs (with Mermaid diagrams and local images) to PDF.

Requires `pip install playwright && playwright install chromium` and network access to
cdn.jsdelivr.net for marked and mermaid.

    python docs/design/render_pdf.py docs/design/prux-assurance-agent-complete-reference.md

The first `# heading` and the paragraph after it become a cover page, `## headings` become
a table of contents, and paragraphs starting with `Figure:` become numbered captions.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
 body { font: 11px/1.55 "Segoe UI", Inter, system-ui, sans-serif; color: #18212f; margin: 0 }
 .cover { height: 250mm; display: flex; flex-direction: column; justify-content: center;
          break-after: page; padding: 0 8mm }
 .cover .band { height: 10px; width: 120px; border-radius: 99px; margin-bottom: 26px;
                background: linear-gradient(90deg,#26165f,#5235d1,#0f8b8d) }
 .cover h1 { font: 700 34px/1.15 Georgia, serif; color: #26165f; border: 0; margin: 0 0 14px }
 .cover .meta { font-size: 13px; color: #334155; max-width: 150mm }
 .cover .date { margin-top: 40px; color: #64748b }
 .toc { break-after: page } .toc h2 { margin-top: 0 }
 .toc ol { font-size: 12.5px; line-height: 2; padding-left: 18px }
 .toc a { color: #18212f; text-decoration: none }
 h1 { font: 700 24px/1.2 Georgia, serif; color: #26165f }
 h2 { font-size: 17px; color: #26165f; margin-top: 26px; padding-bottom: 4px;
      border-bottom: 2px solid #ece9ff; break-after: avoid }
 h3 { font-size: 13px; color: #26165f; break-after: avoid }
 table { border-collapse: collapse; width: 100%; margin: 8px 0; break-inside: avoid }
 th, td { border: 1px solid #cbd5e1; padding: 4px 6px; vertical-align: top; text-align: left }
 th { background: #ece9ff }
 code { font: 10px Consolas, monospace; background: #f1f5f9; padding: 0 3px; border-radius: 3px }
 pre { background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px; border-radius: 6px;
       white-space: pre-wrap; break-inside: avoid }
 pre code { background: none; padding: 0 }
 .mermaid { text-align: center; margin: 12px 0 2px; break-inside: avoid }
 .mermaid svg { max-width: 100%; height: auto; max-height: 205mm }
 p:has(> img) { text-align: center; break-inside: avoid; margin: 10px 0 2px }
 img { max-width: 100%; vertical-align: top }
 p:has(> img:nth-of-type(2)) img { max-width: 49% }
 p:has(> img:nth-of-type(4)) img { max-width: 24.5% }
 p:has(> img:nth-of-type(5)) img { max-width: 19.5% }
 .caption { text-align: center; color: #475569; font-size: 10.5px; font-style: italic;
            margin: 2px 0 14px; break-before: avoid }
 blockquote { border-left: 3px solid #5235d1; margin: 8px 0; padding: 4px 12px; color: #334155;
              background: #f8f7ff }
</style></head><body><main id="doc"></main>
<script>
 (async () => {
   const doc = document.getElementById('doc');
   doc.innerHTML = marked.parse(__MARKDOWN__);
   const title = doc.querySelector('h1');
   if (title) {
     const cover = document.createElement('section');
     cover.className = 'cover';
     const meta = title.nextElementSibling;
     cover.innerHTML = '<div class="band"></div>';
     cover.appendChild(title);
     if (meta && meta.tagName === 'P') { meta.className = 'meta'; cover.appendChild(meta); }
     cover.insertAdjacentHTML('beforeend', '<div class="date">__DATE__</div>');
     doc.prepend(cover);
     const headings = [...doc.querySelectorAll('h2')];
     headings.forEach((h, i) => h.id = 'section-' + i);
     const toc = document.createElement('section');
     toc.className = 'toc';
     toc.innerHTML = '<h2>Contents</h2><ol>' + headings.map((h, i) =>
       `<li><a href="#section-${i}">${h.textContent.replace(/^\\d+[a-z]?\\.\\s*/, '')}</a></li>`).join('') + '</ol>';
     cover.after(toc);
   }
   doc.querySelectorAll('pre > code.language-mermaid').forEach(code => {
     const div = document.createElement('div');
     div.className = 'mermaid';
     div.textContent = code.textContent;
     code.parentElement.replaceWith(div);
   });
   let figure = 0;
   doc.querySelectorAll('p').forEach(p => {
     if (p.textContent.startsWith('Figure:')) {
       figure += 1;
       p.className = 'caption';
       p.innerHTML = p.innerHTML.replace(/^Figure:/, `Figure ${figure} —`);
     }
   });
   mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' });
   try { await mermaid.run({ querySelector: '.mermaid' }); }
   catch (e) { window.renderError = String(e); }
   await Promise.all([...document.images].map(img => img.complete ? null :
     new Promise(resolve => { img.onload = img.onerror = resolve; })));
   window.renderDone = true;
 })();
</script></body></html>"""

FOOTER = (
    '<div style="font-size:8px;width:100%;text-align:center;color:#64748b">'
    "{title} — <span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span></div>"
)


def render(source: Path, target: Path, footer_title: str = "PR-UX Assurance Agent") -> None:
    html = PAGE.replace("__MARKDOWN__", json.dumps(source.read_text(encoding="utf-8")))
    html = html.replace("__DATE__", date.today().strftime("%d %B %Y"))
    staging = source.parent / f".render-{source.stem}.html"
    staging.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(staging.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_function("window.renderDone === true", timeout=60_000)
            error = page.evaluate(
                "window.renderError || (document.body.innerText.includes('Syntax error') "
                "? 'Mermaid syntax error' : null)"
            )
            if error:
                raise RuntimeError(f"Mermaid render failed: {error}")
            broken = page.evaluate("[...document.images].filter(i => !i.naturalWidth).map(i => i.src)")
            if broken:
                raise RuntimeError(f"Images failed to load: {broken}")
            page.pdf(
                path=str(target),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=FOOTER.format(title=footer_title),
            )
            browser.close()
    finally:
        staging.unlink(missing_ok=True)


def render_html_file(source: Path, target: Path, footer_title: str) -> None:
    """Print an existing self-contained HTML file (for example a coverage report) to PDF."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(source.resolve().as_uri(), wait_until="load")
        page.pdf(
            path=str(target),
            format="A4",
            print_background=True,
            margin={"top": "10mm", "bottom": "14mm", "left": "8mm", "right": "8mm"},
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=FOOTER.format(title=footer_title),
        )
        browser.close()


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        markdown_path = Path(argument)
        render(markdown_path, markdown_path.with_suffix(".pdf"))
        print(markdown_path.with_suffix(".pdf"))
