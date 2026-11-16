"""docs/entrega/gerar.py: o Markdown do documento de entrega vira HTML sem perder nada.

Rodar: python3 -m unittest discover -s tests
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gerar", ROOT / "docs" / "entrega" / "gerar.py")
gerar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerar)

BLOCKS = {name: "flowchart TB\n  a --> b" for name in ["arquitetura", *gerar.SAGA_BLOCKS]}


class EntregaTest(unittest.TestCase):
    def test_subconjunto_de_markdown(self):
        page = gerar.to_html("# Título\n\n| A | B |\n|---|---|\n| `x` | **y** |\n\n- um\n  continua\n- dois\n\n"
                             "Texto com [link](https://e.x) e <https://e.y>.\n\n<!-- diagrama: arquitetura -->\n"
                             "\n```mermaid\nflowchart LR\n  c --> d\n```\n\n## Anexo: fim\n", BLOCKS)
        self.assertIn("<h1>Título</h1>", page)
        self.assertIn("<td><code>x</code></td><td><strong>y</strong></td>", page)
        self.assertIn("<li>um continua</li><li>dois</li>", page)
        self.assertIn('<a href="https://e.x">link</a>', page)
        self.assertIn('<a href="https://e.y">https://e.y</a>', page)
        self.assertEqual(page.count('class="mermaid"'), 2)
        self.assertIn("c --&gt; d", page)
        self.assertIn('page-break-before: always', page)

    def test_o_documento_de_verdade_usa_so_diagramas_que_existem(self):
        markdown = (ROOT / "docs" / "entrega" / "ENTREGA-FASE-4.md").read_text(encoding="utf-8")
        page = gerar.to_html(markdown, BLOCKS)  # KeyError se um marcador apontar para diagrama inexistente
        self.assertNotIn("<!-- diagrama", page)
        self.assertNotIn("```", page)


if __name__ == "__main__":
    unittest.main()
