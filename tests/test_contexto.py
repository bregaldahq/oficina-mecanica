"""O contexto que os agentes leem: skills, subagentes e settings do Claude Code.

Rodar: python3 -m unittest discover -s tests
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / ".claude"


def frontmatter(path: Path) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    if not m:
        return {}
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


class ContextoTest(unittest.TestCase):
    def test_skills_tem_nome_igual_ao_diretorio_e_descricao(self):
        skills = sorted(CLAUDE.glob("skills/*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                fm = frontmatter(path)
                self.assertEqual(fm.get("name"), path.parent.name)
                self.assertGreater(len(fm.get("description", "")), 40)

    def test_subagentes_tem_nome_descricao_e_ferramentas(self):
        for path in sorted(CLAUDE.glob("agents/*.md")):
            with self.subTest(agente=path.stem):
                fm = frontmatter(path)
                self.assertEqual(fm.get("name"), path.stem)
                self.assertTrue(fm.get("description"))
                self.assertTrue(fm.get("tools"))
                self.assertNotIn("Edit", fm["tools"].split(", "), "revisor não edita")

    def test_skills_e_subagentes_citados_existem(self):
        names = {p.parent.name for p in CLAUDE.glob("skills/*/SKILL.md")}
        agents = {p.stem for p in CLAUDE.glob("agents/*.md")}
        builtin = {"code-review", "security-review", "simplify", "loop", "fewer-permission-prompts"}
        http = {"api", "docs", "health", "ready"}  # caminhos HTTP que também aparecem entre crases
        for path in [ROOT / "AGENTS.md", ROOT / "CLAUDE.md", *CLAUDE.glob("skills/*/SKILL.md"), *CLAUDE.glob("agents/*.md")]:
            text = path.read_text()
            for cited in set(re.findall(r"`/([a-z][a-z-]+)`", text)) - http:
                with self.subTest(arquivo=path.name, skill=cited):
                    self.assertIn(cited, names | builtin)
            for cited in re.findall(r"subagente `([a-z-]+)`", text):
                with self.subTest(arquivo=path.name, subagente=cited):
                    self.assertIn(cited, agents)

    def test_hooks_do_settings_existem_e_sao_executaveis(self):
        settings = json.loads((CLAUDE / "settings.json").read_text())
        for event, entries in settings["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    script = ROOT / hook["command"].replace('"$CLAUDE_PROJECT_DIR"/', "")
                    with self.subTest(evento=event, hook=script.name):
                        self.assertTrue(script.is_file())
                        self.assertTrue(script.stat().st_mode & 0o111, "sem permissão de execução")


if __name__ == "__main__":
    unittest.main()
