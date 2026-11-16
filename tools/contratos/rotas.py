"""Seção 5: rotas públicas existem nos dois lados, o gateway e a matriz de autorização da app.

Uma rota pública da aplicação só é alcançável pelo API Gateway se tiver rota dedicada sem
authorizer: no `ANY /api/{proxy+}`, sem header Authorization o gateway responde 401 antes de
chamar o jwt-authorizer, então a lista de rotas liberadas do authorizer não basta.
"""
import re

from . import CONTRATOS, CONTRATOS_F4, Finding, Repos, find_line, line_of, md_section, tf_blocks

APIGW = "apigateway.tf"
AUTHORIZER = "src/Handler/JwtAuthorizerHandler.php"
INDEX = "public/index.php"
NGINX = "nginx.conf"
SWAGGER = "swagger.yaml"

# Fase 4: cada integração do gateway aponta para um serviço, e cada serviço tem o próprio nginx.
INTEGRATION_SERVICE = {"app_proxy": "api", "billing_proxy": "faturamento", "execution_proxy": "execucao"}
NGINX_OF = {"api": NGINX, "faturamento": "deploy/base/nginx-configmap.yaml", "execucao": "deploy/base/nginx-configmap.yaml"}
# Rotas internas ficam fora do gateway por desenho (só por dentro da VPC).
INTERNAL = "/internal/"


def norm(route: str) -> str:
    """'POST /api/service-orders/{id}/approval' -> 'POST /api/service-orders/{}/approval'."""
    method, path = route.split(" ", 1)
    return f"{method.upper()} " + re.sub(r"\{(?!proxy\+)[^}]+\}", "{}", path.rstrip("/") or "/")


def gateway_routes(repos: Repos) -> dict[str, dict]:
    """{rota normalizada: {key, public, lambda, line}} do apigateway.tf."""
    text = repos.read("gateway", APIGW)
    integrations = {name: re.search(r'integration_type\s*=\s*"([^"]+)"', body).group(1)
                    for name, body, _ in tf_blocks(text, "resource", "aws_apigatewayv2_integration")
                    if re.search(r'integration_type\s*=\s*"([^"]+)"', body)}
    out = {}
    for _, body, pos in tf_blocks(text, "resource", "aws_apigatewayv2_route"):
        key = re.search(r'route_key\s*=\s*"([^"]+)"', body)
        if not key:
            continue
        auth = re.search(r'authorization_type\s*=\s*"([^"]+)"', body)
        target = re.search(r"aws_apigatewayv2_integration\.(\w+)\.id", body)
        name = target.group(1) if target else ""
        out[norm(key.group(1))] = {
            "key": key.group(1),
            "public": (auth.group(1) if auth else "NONE") == "NONE",
            "lambda": integrations.get(name, "") == "AWS_PROXY",
            "service": INTEGRATION_SERVICE.get(name, "api"),
            "line": line_of(text, pos),
        }
    return out


def service_routes(repos: Repos, service: str) -> dict[str, dict]:
    """{rota normalizada: {key, public, line, service}} do public/index.php de um serviço.

    Os serviços da Fase 4 escrevem `PREFIX . '/health'`; o prefixo vem da constante PREFIX.
    """
    if not repos.has(service):
        return {}
    text = repos.read(service, INDEX)
    prefix = re.search(r"const\s+PREFIX\s*=\s*'([^']+)'", text)
    out = {}
    for m in re.finditer(r"\$router->(get|post|put|patch|delete)\(\s*(PREFIX\s*\.\s*)?'([^']+)'(.*?);", text, re.S):
        path = (prefix.group(1) if m.group(2) and prefix else "") + m.group(3)
        key = f"{m.group(1).upper()} {path}"
        out[norm(key)] = {"key": key, "public": "requireAuth: false" in m.group(4), "line": line_of(text, m.start()),
                          "service": service, "internal": path.startswith(INTERNAL)}
    return out


def app_routes(repos: Repos) -> dict[str, dict]:
    """{rota normalizada: {key, public, line}} declaradas em public/index.php do serviço de OS."""
    return service_routes(repos, "api")


def authorizer_public(repos: Repos) -> dict[str, int]:
    text = repos.read("gateway", AUTHORIZER)
    return {norm(f"{m.group(1)} {m.group(2)}"): line_of(text, m.start())
            for m in re.finditer(r"'method'\s*=>\s*'(\w+)',\s*'path'\s*=>\s*'([^']+)'", text)}


def nginx_serves(repos: Repos, path: str, service: str = "api") -> bool:
    if not repos.has(service):
        return False
    text = repos.read(service, NGINX_OF[service])
    prefix = path.replace("{proxy+}", "").rstrip("/") or "/"
    for m in re.finditer(r"location\s+(=\s*)?(\S+)\s*\{", text):
        exact, loc = m.group(1), m.group(2)
        if (exact and loc == prefix) or (not exact and loc != "/" and prefix.startswith(loc.rstrip("/"))):
            return True
    return False


ROUTE = r"(?:GET|POST|PUT|PATCH|DELETE|ANY) [^`]+"


def removed_in_f4(repos: Repos) -> set[str]:
    """Rotas que a seção 4 do CONTRATOS da Fase 4 marca como removidas."""
    if not repos.exists("api", CONTRATOS_F4):
        return set()
    section = md_section(repos.read("api", CONTRATOS_F4), 4)
    out = set()
    for block in re.finditer(r"\*\*Removid[ao]s?[^*]*\*\*(.*?)(?:\n\n(?!-)|\n###|\Z)", section, re.S):
        out |= {norm(r) for r in re.findall(rf"`({ROUTE})`", block.group(1))}
    return out


def documented_gateway(repos: Repos) -> dict[str, tuple[bool, int]]:
    """{rota: (pública?, linha)} da tabela "API Gateway" da seção 5, com a da Fase 4 (§4)."""
    text = repos.read("api", CONTRATOS)
    section = md_section(text, 5)
    table = section.split("### Aplicação")[0]
    base = text.find(section)
    out = {norm(m.group(1)): ("nenhum" in m.group(2).lower(), line_of(text, base + m.start()))
           for m in re.finditer(rf"^\| `({ROUTE})` \|[^|]*\|([^|]*)\|", table, re.M)}
    if repos.exists("api", CONTRATOS_F4):
        f4 = repos.read("api", CONTRATOS_F4)
        section = md_section(f4, 4)
        table = section.split("### OS")[0]
        base = f4.find(section)
        for row in re.finditer(r"^\| (`[^|]+) \|[^|]*\|([^|]*)\|", table, re.M):
            for route in re.findall(rf"`({ROUTE})`", row.group(1)):
                out[norm(route)] = ("nenhum" in row.group(2).lower(), line_of(f4, base + row.start()))
        for route in removed_in_f4(repos):
            out.pop(route, None)
    return out


def documented_app_public(repos: Repos) -> dict[str, int]:
    """Rotas da matriz da aplicação (seção 5) que não exigem JWT: públicas ou por X-Webhook-Token."""
    text = repos.read("api", CONTRATOS)
    section = md_section(text, 5)
    part = section.split("### Aplicação")[1].split("###")[0] if "### Aplicação" in section else ""
    base = text.find(part) if part else 0
    return {norm(m.group(1)): line_of(text, base + m.start())
            for m in re.finditer(r"^\| `((?:GET|POST|PUT|PATCH|DELETE) [^`]+)` \|([^|]*)\|", part, re.M)
            if re.search(r"público|X-Webhook-Token", m.group(2))}


def swagger_public(repos: Repos) -> dict[str, int]:
    """Operações com `security: []` no swagger.yaml, como 'MÉTODO /caminho' (sem o /api dos servers)."""
    out, path, method = {}, None, None
    for i, line in enumerate(repos.read("api", SWAGGER).splitlines(), 1):
        if m := re.match(r"^  (/\S*):\s*$", line):
            path, method = m.group(1), None
        elif path and (m := re.match(r"^    (get|post|put|patch|delete):\s*$", line)):
            method = m.group(1).upper()
        elif path and method and re.match(r"^      security:\s*\[\]\s*$", line):
            out[norm(f"{method} {path}")] = i
        elif re.match(r"^\S", line):
            path, method = (None, None) if not line.startswith("paths:") else (path, method)
    return out


def check(repos: Repos) -> list[Finding]:
    if not repos.has("gateway", "api"):
        return []
    out = []
    gw, authz = gateway_routes(repos), authorizer_public(repos)
    services = {s: service_routes(repos, s) for s in ("api", "faturamento", "execucao")}
    app = {r: a for r, a in services["api"].items() if not a["internal"]}
    gw_text = repos.read("gateway", APIGW)

    # Toda rota pública de um serviço tem rota dedicada sem authorizer, apontando para ele.
    for service, routes in services.items():
        for route, a in routes.items():
            if a["internal"] or not a["public"]:
                continue
            if not (route in gw and gw[route]["public"] and gw[route]["service"] == service):
                out.append(Finding("ROTA-1", "erro", "§5", f"{a['key']} é pública em {repos.name(service)}, mas não tem rota dedicada sem "
                                   "authorizer no gateway para esse serviço: pelo proxy o gateway exige Authorization e a rota "
                                   "fica inalcançável de fora", a["key"],
                                   [repos.at(service, INDEX, a["line"]), repos.at("gateway", APIGW, find_line(gw_text, '"ANY /api/{proxy+}"'))]))

    for route, g in gw.items():
        path = route.split(" ", 1)[1]
        if path.startswith(INTERNAL):
            out.append(Finding("ROTA-5", "erro", "§4", f"o gateway expõe {g['key']}, mas rota interna só é alcançável por dentro da VPC",
                               g["key"], [repos.at("gateway", APIGW, g["line"])]))
            continue
        if not g["public"] or g["lambda"]:
            continue
        service = g["service"]
        if not repos.has(service):
            continue
        routes = services[service]
        if route in routes:
            if not routes[route]["public"]:
                out.append(Finding("ROTA-1", "erro", "§5", f"{g['key']} é pública no gateway, mas {repos.name(service)} exige JWT: responde 401",
                                   g["key"], [repos.at("gateway", APIGW, g["line"]), repos.at(service, INDEX, routes[route]["line"])]))
        elif not nginx_serves(repos, path, service):
            what = "a aplicação não declara essa rota" if path.startswith("/api/") else f"o nginx não serve {path}"
            out.append(Finding("ROTA-1", "erro", "§5", f"o gateway encaminha {g['key']} para {repos.name(service)}, mas {what}",
                               g["key"], [repos.at("gateway", APIGW, g["line"]), repos.at(service, INDEX)]))
    for route, line in authz.items():
        if route in app and not app[route]["public"]:
            out.append(Finding("ROTA-1", "erro", "§5", f"o jwt-authorizer libera {route} sem token, mas a aplicação exige JWT",
                               route, [repos.at("gateway", AUTHORIZER, line), repos.at("api", INDEX, app[route]["line"])]))

    doc_gw = documented_gateway(repos)
    if doc_gw:
        for route in sorted(set(gw) | set(doc_gw)):
            if route not in doc_gw:
                out.append(Finding("ROTA-2", "aviso", "§5", f"o gateway tem {gw[route]['key']}"
                                   f"{' (sem authorizer)' if gw[route]['public'] else ''}, mas a tabela do API Gateway no CONTRATOS.md não",
                                   gw[route]["key"], [repos.at("gateway", APIGW, gw[route]["line"]), repos.at("api", CONTRATOS, find_line(repos.read("api", CONTRATOS), "### API Gateway"))]))
            elif route not in gw:
                out.append(Finding("ROTA-2", "aviso", "§5", f"o CONTRATOS.md lista {route} no gateway, mas o apigateway.tf não tem essa rota",
                                   route, [repos.at("api", CONTRATOS, doc_gw[route][1])]))
            elif doc_gw[route][0] != gw[route]["public"]:
                out.append(Finding("ROTA-2", "aviso", "§5", f"{route}: o CONTRATOS.md e o apigateway.tf discordam sobre o authorizer",
                                   route, [repos.at("api", CONTRATOS, doc_gw[route][1]), repos.at("gateway", APIGW, gw[route]["line"])]))

    doc_app = {r: line for r, line in documented_app_public(repos).items() if r not in removed_in_f4(repos)}
    app_public = {r for r, a in app.items() if a["public"]}
    if doc_app:
        for route in sorted(app_public ^ set(doc_app)):
            where = [repos.at("api", INDEX, app[route]["line"])] if route in app else []
            where.append(repos.at("api", CONTRATOS, doc_app.get(route, find_line(repos.read("api", CONTRATOS), "### Aplicação"))))
            out.append(Finding("ROTA-3", "aviso", "§5", f"{route}: {'pública na aplicação e fora' if route in app_public else 'sem JWT no CONTRATOS.md e protegida'}"
                               f"{' da matriz do CONTRATOS.md' if route in app_public else ' na aplicação'}", route, where))

    expected = {r.replace(" /api/", " /", 1) for r in app_public} | {r for r, g in gw.items() if g["public"] and g["lambda"]}
    documented = swagger_public(repos)
    if documented:
        for route in sorted(expected ^ set(documented)):
            msg = "é pública, mas o swagger.yaml exige autenticação ou não documenta" if route in expected else \
                  "tem `security: []` no swagger.yaml, mas exige autenticação"
            out.append(Finding("ROTA-4", "aviso", "§5", f"{route} {msg}", route,
                               [repos.at("api", SWAGGER, documented.get(route, 0))]))
    return out
