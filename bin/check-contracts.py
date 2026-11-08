#!/usr/bin/env python3
"""Confere se os quatro repositórios obedecem ao CONTRATOS.md (docs/fase-3 da aplicação).

Famílias de checagem (código em tools/contratos/):

  ssm         §2  parâmetro consumido sem dono, com dois donos, sem consumidor, fora do documento
  jwt         §4  token literal igual nos dois testes de contrato e no contract-token.md;
                  montagem do token equivalente nos dois JwtProvider
  rotas       §5  rota pública da app com rota dedicada no gateway, e vice-versa; authorizer;
                  tabelas do CONTRATOS.md e security: [] do swagger.yaml
  segredos    §3  chaves lidas pelo ExternalSecret, pela Lambda e pelo smoke test existem no
                  secrets.tf; documento
  k8s         ClusterSecretStore, RBAC das CRDs da app, placeholders do deploy.yml
  migrations  §6  nome e sequência, SQL proibido, seed só _demo; colunas faltando no schema
                  SQLite dos testes de integração
  nomes       nomes antigos (state, role de CI, tag Repo), tags obrigatórias, OIDC, versão do
              Terraform
  docs        caminhos citados no AGENTS.md, README, CLAUDE.md e .claude/ existem

erro = as implementações discordam e algo quebra; aviso = o documento está desatualizado;
conhecido = erro aceito, com motivo, em tools/contratos/conhecidos.txt.

Uso: bin/check-contracts.py [--json] [--only ssm,rotas,...] [--verbose]
Sai com 1 se houver erro (não conhecido). Vale a branch que estiver em disco em cada repo.
"""
import argparse
import json
import sys
from pathlib import Path

from wslib import ROOT, repos_dir

sys.path.insert(0, str(ROOT / "tools"))
import contratos  # noqa: E402
from contratos import REPOS, ssm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()
    if args.help:
        print(__doc__.strip())
        return 0

    base = repos_dir()
    repos = contratos.Repos({short: base / new for short, (new, _) in REPOS.items()}, ROOT)
    missing = [REPOS[s][0] for s in REPOS if not repos.has(s)]
    if len(missing) == len(REPOS):
        print("Nenhum repositório em repos/. Rode bin/ws clone primeiro.")
        return 1

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    if only and only - set(contratos.FAMILIES):
        print(f"família desconhecida: {', '.join(sorted(only - set(contratos.FAMILIES)))} "
              f"(opções: {', '.join(contratos.FAMILIES)})")
        return 2
    findings = contratos.run(repos, only)
    errors = sum(f.severidade == "erro" for f in findings)
    count = {s: sum(f.severidade == s for f in findings) for s in ("erro", "conhecido", "aviso")}

    if args.json:
        print(json.dumps({"ok": errors == 0, "ausentes": missing, "contagem": count,
                          "achados": [f.as_dict() for f in findings]}, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    for name in missing:
        print(f"aviso     {name} ausente em {base}: as checagens que dependem dele foram puladas")
    for f in findings:
        print(f"{f.severidade.upper() if f.severidade != 'aviso' else 'aviso':<9} {f.id:<8} {f.secao:<6} {f.mensagem}")
        for loc in f.locais:
            print(f"{'':<25}{loc}")

    if args.verbose:
        producers, consumers = ssm.inventory(repos)
        print()
        for name in sorted(set(producers) | set(consumers)):
            print(f"/oficina/<env>/{name}")
            print(f"   publica: {', '.join(REPOS[s][0] for s in producers.get(name, {})) or '-'}")
            print(f"   consome: {', '.join(REPOS[s][0] for s in consumers.get(name, {})) or '-'}")

    print(f"\n{count['erro']} erro(s), {count['conhecido']} conhecido(s), {count['aviso']} aviso(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
