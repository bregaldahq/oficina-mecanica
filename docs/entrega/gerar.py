#!/usr/bin/env python3
"""Gera o documento de entrega da Fase 4: ENTREGA-FASE-4.md -> .html -> .pdf.

O Markdown é a fonte; edite só ele. Bloco ```mermaid no próprio documento vira diagrama. Cada
`<!-- diagrama: <nome> -->` vira o diagrama Mermaid de
mesmo nome dos arquivos em oficina-api/docs/fase-4/diagramas/ (o primeiro bloco de
arquitetura.md, e os blocos de saga.md na ordem: caminho feliz, reparo que falha, todas as
falhas, status da OS). O HTML carrega o Mermaid do jsDelivr para desenhar os diagramas.

O PDF sai do Chrome (ou do Edge) em modo headless: no WSL, o do Windows; no Linux, o
`google-chrome`/`chromium` do PATH. Sem navegador, abra o HTML e imprima em PDF.

Uso: python3 docs/entrega/gerar.py [--sem-pdf]
"""
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bin"))

SOURCE = HERE / "ENTREGA-FASE-4.md"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
SAGA_BLOCKS = ["saga-caminho-feliz", "saga-reparo-falha", "saga-todas-as-falhas", "status-da-os"]
BROWSERS = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]

CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Segoe UI", Roboto, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1d2433; }
h1 { font-size: 20pt; margin: 0 0 4pt; color: #0b3d6b; }
h2, h3 { break-after: avoid; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; color: #0b3d6b; border-bottom: 1px solid #c9d3e0; padding-bottom: 2pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; }
p, ul { margin: 4pt 0 6pt; }
li { margin: 2pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 8pt; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #c9d3e0; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef2f7; }
code { font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f2f4f7; padding: 0 2px; }
a { color: #0b5cad; text-decoration: none; }
.diagrama { text-align: center; margin: 8pt 0; page-break-inside: avoid; }
.diagrama svg { max-width: 100%; height: auto; max-height: 230mm; }
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', out)
    return out


def diagrams() -> dict[str, str]:
    from wslib import repos_dir

    base = repos_dir() / "oficina-api" / "docs" / "fase-4" / "diagramas"
    blocks = {"arquitetura": re.findall(r"```mermaid\n(.*?)```", (base / "arquitetura.md").read_text(encoding="utf-8"), re.S)[0]}
    saga = re.findall(r"```mermaid\n(.*?)```", (base / "saga.md").read_text(encoding="utf-8"), re.S)
    blocks.update(zip(SAGA_BLOCKS, saga))
    return blocks


def to_html(markdown: str, blocks: dict[str, str]) -> str:
    """O subconjunto de Markdown que o documento usa: títulos, parágrafos, listas, tabelas."""
    body: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.strip() == "```mermaid":  # diagrama escrito no próprio documento
            end = lines.index("```", i + 1)
            source = "\n".join(lines[i + 1:end])
            body.append(f'<div class="diagrama"><pre class="mermaid">{html.escape(source)}</pre></div>')
            i = end + 1
        elif m := re.match(r"<!-- diagrama: ([\w-]+) -->", line.strip()):
            body.append(f'<div class="diagrama"><pre class="mermaid">{html.escape(blocks[m.group(1)])}</pre></div>')
            i += 1
        elif m := re.match(r"(#{1,3}) (.*)", line):
            level = len(m.group(1))
            # O anexo abre página nova: o título não fica separado do diagrama.
            attr = ' style="page-break-before: always"' if m.group(2).startswith("Anexo") else ""
            body.append(f"<h{level}{attr}>{inline(m.group(2))}</h{level}>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, rest = rows[0], [r for r in rows[2:]]
            thead = "" if not any(head) else "<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>"
            tbody = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rest)
            body.append(f"<table>{thead}<tbody>{tbody}</tbody></table>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  ")):
                if lines[i].startswith("- "):
                    items.append(lines[i][2:].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            body.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||- |<!--)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            body.append(f"<p>{inline(' '.join(para))}</p>")
    title = re.sub(r"<[^>]+>", "", body[0]) if body else "Entrega"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style>
<script src="{MERMAID}"></script>
<script>mermaid.initialize({{ startOnLoad: true, theme: "default", flowchart: {{ htmlLabels: true }} }});</script>
</head><body>
{chr(10).join(body)}
</body></html>
"""


def browser() -> str | None:
    for candidate in BROWSERS:
        if Path(candidate).is_file() or shutil.which(candidate):
            return candidate
    return None


def print_pdf(page: Path, pdf: Path) -> bool:
    exe = browser()
    if exe is None:
        print("sem Chrome/Edge: abra o HTML no navegador e imprima em PDF")
        return False
    windows = exe.startswith("/mnt/")
    path = (lambda p: subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True).stdout.strip()) if windows else str
    url = ("file:///" + path(page).replace("\\", "/")) if windows else page.as_uri()
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=15000",
                    f"--print-to-pdf={path(pdf)}", url], capture_output=True, timeout=120)
    return pdf.is_file() and pdf.stat().st_size > 0


def main() -> int:
    page = SOURCE.with_suffix(".html")
    page.write_text(to_html(SOURCE.read_text(encoding="utf-8"), diagrams()), encoding="utf-8")
    print(f"HTML: {page.relative_to(ROOT)}")
    if "--sem-pdf" in sys.argv:
        return 0
    pdf = SOURCE.with_suffix(".pdf")
    if print_pdf(page, pdf):
        print(f"PDF:  {pdf.relative_to(ROOT)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
