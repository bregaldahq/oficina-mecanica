"""bin/e2e_fase4.py: o que dá para conferir sem subir containers.

Rodar: python3 -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import e2e_fase4  # noqa: E402


class Fase4E2ETest(unittest.TestCase):
    def make(self, repos: Path) -> e2e_fase4.Fase4E2E:
        with mock.patch.object(e2e_fase4, "repos_dir", return_value=repos):
            return e2e_fase4.Fase4E2E(lambda *a, **k: True)

    def test_so_roda_quando_o_servico_tem_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            e2e = self.make(Path(tmp))
            self.assertFalse(e2e.available())
            (Path(tmp) / "oficina-execucao" / "bin").mkdir(parents=True)
            (Path(tmp) / "oficina-execucao" / "bin" / "worker.php").write_text("<?php")
            self.assertTrue(e2e.available())

    def test_resultados_do_worker_saem_das_linhas_de_log(self):
        e2e = self.make(Path("/nao-existe"))
        logs = [{"message": "worker.started"}, {"message": "message.processed", "outcome": "ok"},
                {"message": "message.processed", "outcome": "duplicate"}, {"message": "worker.stopped"}]
        self.assertEqual(e2e.outcomes(logs), ["ok", "duplicate"])

    def test_a_sonda_escuta_exatamente_os_eventos_da_execucao_no_contrato(self):
        contrato = ROOT / "repos" / "oficina-api" / "docs" / "fase-4" / "CONTRATOS.md"
        if not contrato.is_file():
            self.skipTest("contrato da Fase 4 não está em disco")
        import re
        tipos = re.findall(r"^\| `([a-z-]+\.[a-z-]+)` \| execucao → os \|", contrato.read_text(), re.M)
        self.assertEqual(sorted(tipos), sorted(e2e_fase4.EXECUTION_EVENTS))

    def test_o_ambiente_local_nao_tem_credencial_de_verdade(self):
        e2e = self.make(Path("/nao-existe"))
        self.assertNotIn("AWS_ACCESS_KEY_ID", e2e.env)
        self.assertTrue(e2e.env["AWS_ENDPOINT_URL"].startswith("http://oficina-e2e4-"))


if __name__ == "__main__":
    unittest.main()
