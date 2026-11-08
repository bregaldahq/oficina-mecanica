"""Seção 6: as migrations da fundação, que o Job da aplicação executa.

MIG-1  NNN_<slug>.sql em sequência, sem CREATE DATABASE, USE ou DELIMITER; seed só como _demo
MIG-2  coluna das migrations que um repositório PDO usa e que falta no schema SQLite escrito à
       mão nos testes de integração
"""
import re

from . import Finding, Repos, line_of

NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
FORBIDDEN = re.compile(r"^\s*(CREATE DATABASE|USE |DELIMITER)", re.I | re.M)
TYPES = r"(?:INT|INTEGER|BIGINT|SMALLINT|TINYINT|VARCHAR|CHAR|TEXT|LONGTEXT|MEDIUMTEXT|ENUM|DECIMAL|NUMERIC|" \
        r"DATETIME|TIMESTAMP|DATE|BOOLEAN|BOOL|JSON|DOUBLE|FLOAT|REAL|BLOB|BINARY|VARBINARY)"
COLUMN = re.compile(rf"^\s*`?(\w+)`?\s+{TYPES}\b", re.I | re.M)


def tables(sql: str) -> dict[str, set[str]]:
    """{tabela: colunas} dos CREATE TABLE e dos ALTER TABLE ... ADD COLUMN de um texto SQL."""
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?\s*\(", sql, re.I):
        depth, i = 1, m.end()
        while i < len(sql) and depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        cols = {c.lower() for c in COLUMN.findall(sql[m.end():i - 1])}
        out.setdefault(m.group(1).lower(), set()).update(cols - {"primary", "key", "unique", "index", "constraint", "foreign"})
    for table, col in re.findall(r"ALTER TABLE\s+`?(\w+)`?\s+ADD COLUMN\s+`?(\w+)`?", sql, re.I):
        out.setdefault(table.lower(), set()).add(col.lower())
    return out


def check(repos: Repos) -> list[Finding]:
    if not repos.has("fundacao"):
        return []
    out = []
    files = sorted(rel for rel in repos.tracked("fundacao") if rel.startswith("migrations/") and rel.endswith(".sql"))
    numbers = []
    for rel in files:
        base = rel.split("/", 1)[1]
        m = NAME.match(base)
        if not m:
            out.append(Finding("MIG-1", "erro", "§6", f"{base} não segue NNN_<slug>.sql: o runner ordena pelo nome",
                               base, [repos.at("fundacao", rel)]))
            continue
        numbers.append((int(m.group(1)), rel))
        text = repos.read("fundacao", rel)
        for bad in FORBIDDEN.finditer(text):
            out.append(Finding("MIG-1", "erro", "§6", f"{base} usa '{bad.group(1).strip()}', proibido nas migrations",
                               f"{base} {bad.group(1).strip().upper()}", [repos.at("fundacao", rel, line_of(text, bad.start()))]))
        if "seed" in base and not base.endswith("_demo.sql"):
            out.append(Finding("MIG-1", "erro", "§6", f"{base} parece seed, mas não termina em _demo: rodaria em produção",
                               base, [repos.at("fundacao", rel)]))
    seen = {}
    for n, rel in numbers:
        if n in seen:
            out.append(Finding("MIG-1", "erro", "§6", f"duas migrations com o número {n:03d}", f"{n:03d}",
                               [repos.at("fundacao", seen[n]), repos.at("fundacao", rel)]))
        seen[n] = rel
    expected = list(range(1, len(seen) + 1))
    if sorted(seen) != expected:
        gaps = sorted(set(range(1, max(seen, default=0) + 1)) - set(seen))
        if gaps:
            out.append(Finding("MIG-1", "erro", "§6", f"falta(m) a(s) migration(s) {', '.join(f'{g:03d}' for g in gaps)} na sequência",
                               "sequencia", [repos.at("fundacao", "migrations/")]))

    if repos.has("api"):
        migrated: dict[str, set[str]] = {}
        for _, rel in numbers:
            for t, cols in tables(repos.read("fundacao", rel)).items():
                migrated.setdefault(t, set()).update(cols)
        in_tests: dict[str, tuple[set[str], str]] = {}
        for rel in repos.tracked("api"):
            if rel.startswith("tests/Integration/") and rel.endswith(".php"):
                for t, cols in tables(repos.read("api", rel)).items():
                    in_tests.setdefault(t, (set(), rel))[0].update(cols)
        used = " ".join(repos.read("api", rel) for rel in repos.tracked("api")
                        if rel.startswith("src/Infrastructure/Repository/") and rel.endswith(".php"))
        for table, (cols, rel) in sorted(in_tests.items()):
            for col in sorted(migrated.get(table, set()) - cols):
                if re.search(rf"\b{col}\b", used):
                    out.append(Finding("MIG-2", "aviso", "§6", f"{table}.{col} existe nas migrations e é usada pelos "
                                       "repositórios PDO, mas falta no CREATE TABLE dos testes de integração",
                                       f"{table}.{col}", [repos.at("api", rel)]))
    return out
