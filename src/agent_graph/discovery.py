"""Closed AST grammar for HTTP requests; absence of extraction is not independence."""
from __future__ import annotations

import ast
import re
from urllib.parse import parse_qs, urlsplit

from .contracts import Policy, digest, load_json

METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def evidence(source, node=None, start=None, end=None):
    first = start or getattr(node, "lineno", 1)
    last = end or getattr(node, "end_lineno", first)
    lines = source["text"].splitlines()
    return dict(source_id=source["id"], start_line=first, end_line=last,
                quote="\n".join(lines[first-1:last]))


def operation_id(policy, service, method, path):
    return digest([policy.installation_id, policy.environment, service, method.upper(), path])


def constant(node, constants):
    if isinstance(node, ast.Constant) and (node.value is None or type(node.value) in (str, int)):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = constant(node.left, constants), constant(node.right, constants)
        if type(a) is str and type(b) is str:
            return a + b
    return UNRESOLVED


UNRESOLVED = object()


def module_constants(tree):
    stores = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            stores[node.id] = stores.get(node.id, 0) + 1
        if isinstance(node, ast.arg):
            stores[node.arg] = stores.get(node.arg, 0) + 1
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if stores.get(name) == 1:
                value = constant(node.value, constants)
                if value is not UNRESOLVED:
                    constants[name] = value
    return constants


def imports(tree):
    modules, functions = set(), {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            modules.update(a.asname or a.name for a in n.names if a.name == "requests")
        if isinstance(n, ast.ImportFrom) and n.module == "requests":
            functions.update({a.asname or a.name: a.name for a in n.names if a.name in METHODS | {"request"}})
    return modules, functions


def providers(policy, sources):
    operations, gaps = [], []
    for source in sources.values():
        if source["path"].endswith(".json"):
            try:
                data = load_json(source["text"])
                if not isinstance(data, dict) or "openapi" not in data:
                    continue
                for path, item in data.get("paths", {}).items():
                    if not path.startswith("/") or not isinstance(item, dict):
                        continue
                    if "$ref" in item:
                        gaps.append(dict(code="openapi_ref_unsupported", source_id=source["id"]))
                    for method, operation in item.items():
                        if method not in METHODS or not isinstance(operation, dict):
                            continue
                        op = dict(id=operation_id(policy, source["service"], method, path),
                                  service=source["service"], method=method.upper(), path=path,
                                  evidence=[evidence(source)], default_known=False)
                        for p in operation.get("parameters", []) + item.get("parameters", []):
                            if "$ref" in p:
                                gaps.append(dict(code="openapi_ref_unsupported", source_id=source["id"]))
                            if p.get("name") == "page_size" and isinstance(p.get("schema"), dict):
                                value = p["schema"].get("default", UNRESOLVED)
                                if value is None or type(value) is int:
                                    op.update(default_known=True, page_size_default=value)
                        operations.append(op)
            except (ValueError, TypeError, AttributeError):
                gaps.append(dict(code="invalid_contract", source_id=source["id"]))
        if not source["path"].endswith(".py"):
            continue
        try:
            tree = ast.parse(source["text"])
        except (SyntaxError, ValueError, RecursionError):
            gaps.append(dict(code="python_parse_error", source_id=source["id"]))
            continue
        fastapi = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                   and n.module == "fastapi" for a in n.names if a.name == "FastAPI"}
        apps = {n.targets[0].id for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id in fastapi}
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for d in fn.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and isinstance(d.func.value, ast.Name) and d.func.value.id in apps
                        and (fn not in tree.body or d.func.attr not in METHODS
                             or not d.args or not isinstance(d.args[0], ast.Constant)
                             or not isinstance(d.args[0].value, str))):
                    gaps.append(dict(code="provider_route_unsupported", source_id=source["id"]))
        for fn in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for d in fn.decorator_list:
                if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and isinstance(d.func.value, ast.Name) and d.func.value.id in apps
                        and d.func.attr in METHODS and d.args and isinstance(d.args[0], ast.Constant)
                        and isinstance(d.args[0].value, str)):
                    continue
                path, method = d.args[0].value, d.func.attr.upper()
                op = dict(id=operation_id(policy, source["service"], method, path),
                          service=source["service"], method=method, path=path,
                          evidence=[evidence(source, fn)], default_known=False)
                args = fn.args.posonlyargs + fn.args.args
                defaults = dict(zip([a.arg for a in args][-len(fn.args.defaults):], fn.args.defaults)) if fn.args.defaults else {}
                defaults.update({a.arg: value for a, value in zip(fn.args.kwonlyargs, fn.args.kw_defaults) if value is not None})
                if "page_size" in defaults:
                    value = constant(defaults["page_size"], {})
                    if value is None or type(value) is int:
                        op.update(default_known=True, page_size_default=value)
                operations.append(op)
    grouped = {}
    for op in operations:
        if op["id"] not in grouped:
            grouped[op["id"]] = op
            continue
        old = grouped[op["id"]]
        old["evidence"].extend(op["evidence"])
        if old["default_known"] and op["default_known"] and old["page_size_default"] != op["page_size_default"]:
            old["default_conflict"] = True
            gaps.append(dict(code="provider_declaration_conflict", operation_id=op["id"]))
        elif op["default_known"]:
            old.update(default_known=True, page_size_default=op["page_size_default"])
    return sorted(grouped.values(), key=lambda o: o["id"]), gaps


def match_url(policy, operations, method, url):
    try:
        u = urlsplit(url)
        if u.username or u.password or u.fragment or u.scheme not in ("http", "https"):
            return [], "unsupported_url"
        candidates = []
        for address in policy.addresses:
            base = urlsplit(address.base_url)
            if (u.scheme, u.hostname, u.port) != (base.scheme, base.hostname, base.port):
                continue
            if base.path and not u.path.startswith(base.path + "/"):
                continue
            path = u.path[len(base.path):] or "/"
            ops = [o for o in operations if o["service"] == address.service and o["method"] == method]
            exact = [o for o in ops if o["path"] == path]
            templates = [o for o in ops if re.fullmatch(re.sub(r"\\\{[^{}]+\\\}", "[^/]+", re.escape(o["path"])), path)]
            candidates.extend(exact or templates)
        candidates = list({o["id"]: o for o in candidates}.values())
        return candidates, "ambiguous_mapping" if len(candidates) > 1 else "unmapped_call"
    except (ValueError, TypeError):
        return [], "unsupported_url"


def consumers(policy: Policy, sources, operations):
    dependencies, gaps = [], []
    for source in sources.values():
        if not source["path"].endswith(".py"):
            continue
        try:
            tree = ast.parse(source["text"])
        except (SyntaxError, ValueError, RecursionError):
            continue  # provider pass already records parse failures
        modules, functions = imports(tree)
        constants = module_constants(tree)
        # Rebinding an imported name anywhere is outside this conservative grammar.
        rebound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        rebound.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            name = None
            if (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in modules):
                name = call.func.attr
                if call.func.value.id in rebound:
                    name = "unsupported"
            if isinstance(call.func, ast.Name) and call.func.id in functions:
                name = functions[call.func.id] if call.func.id not in rebound else "unsupported"
            if name is None:
                # Detect common unsupported clients/wrappers without pretending
                # to enumerate every possible Python call mechanism.
                if isinstance(call.func, ast.Attribute) and call.func.attr in METHODS | {"request"}:
                    gaps.append(dict(code="unknown_http_client", evidence=evidence(source, call)))
                continue
            url_node = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "url"), None)
            method = name.upper()
            if name == "request":
                method_node = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "method"), None)
                method_value = constant(method_node, constants)
                method = method_value.upper() if isinstance(method_value, str) else "UNKNOWN"
                url_node = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "url"), None)
            url = constant(url_node, constants)
            if name not in METHODS | {"request"} or not isinstance(url, str) or method.lower() not in METHODS:
                gaps.append(dict(code="dynamic_or_unsupported_call", evidence=evidence(source, call)))
                continue
            matches, reason = match_url(policy, operations, method, url)
            if len(matches) != 1:
                gaps.append(dict(code=reason, evidence=evidence(source, call)))
                continue
            fn = call
            in_loop = False
            while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                fn = parents[fn]
                in_loop |= isinstance(fn, (ast.While, ast.For, ast.AsyncFor, ast.comprehension))
            # kwargs expansion can hide an explicit page size or cursor.
            params = next((k.value for k in call.keywords if k.arg == "params"), None)
            unknown_kwargs = any(k.arg is None for k in call.keywords)
            params_known = params is None or isinstance(params, ast.Dict) and all(isinstance(k, ast.Constant) for k in params.keys)
            keys = [k.value for k in params.keys] if isinstance(params, ast.Dict) and params_known else []
            has_cursor_read = any(isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                                  and n.slice.value == "next_cursor" for n in ast.walk(fn))
            usage = "SINGLE_REQUEST_OBSERVED"
            if unknown_kwargs or not params_known:
                usage = "UNKNOWN_USAGE"
                gaps.append(dict(code="dynamic_parameters", evidence=evidence(source, call)))
            elif in_loop and "cursor" in keys and has_cursor_read:
                usage = "CURSOR_LOOP_OBSERVED"
            elif in_loop:
                usage = "UNKNOWN_USAGE"
            elif "page_size" in keys or "page_size" in parse_qs(urlsplit(url).query):
                usage = "EXPLICIT_PAGE_SIZE"
            op = matches[0]
            dep = dict(id=digest([op["id"], source["repository"], source["path"], call.lineno]),
                       operation_id=op["id"], consumer=source["service"], repository=source["repository"],
                       path=source["path"], call_line=call.lineno, status="STATIC_RESOLVED", usage=usage,
                       environment=policy.environment, evidence=[evidence(source, call)],
                       usage_evidence=[evidence(source, fn)])
            dependencies.append(dep)
    return sorted(dependencies, key=lambda d: d["id"]), gaps


def extract(policy, collected):
    operations, pgaps = providers(policy, collected["sources"])
    deps, cgaps = consumers(policy, collected["sources"], operations)
    rules, candidates = [], []
    by_path = {(s["repository"], s["path"]): s for s in collected["sources"].values()}
    for requirement in policy.requirements:
        source = by_path.get((requirement.repository, requirement.path))
        if not source or source["sha256"] != requirement.sha256:
            pgaps.append(dict(code="requirement_basis_stale", requirement_id=requirement.id))
            continue
        rules.append({**requirement.model_dump(), "kind": "APPROVED_REQUIREMENT",
                      "operation_id": operation_id(policy, requirement.service, requirement.method, requirement.path_template),
                      "evidence": [evidence(source)]})
    # Tests/notes are observations, regardless of instructions or approval words.
    for source in collected["sources"].values():
        if source["path"].endswith(".md"):
            candidates.append(dict(kind="UNTRUSTED_NOTE", evidence=[evidence(source)]))
        if source["path"].endswith(".py") and source["path"].split("/")[-1].startswith("test_"):
            candidates.append(dict(kind="TEST_SOURCE_OBSERVATION", evidence=[evidence(source)]))
    conflicts = []
    for rule in rules:
        for other in rules:
            if (rule["id"] < other["id"] and rule["operation_id"] == other["operation_id"]
                    and rule["consumer"] == other["consumer"] and rule["predicate"] != other["predicate"]):
                conflicts.append([rule["id"], other["id"]])
    return dict(operations=operations, dependencies=deps, requirements=rules, candidates=candidates,
                conflicts=conflicts, gaps=collected["gaps"] + pgaps + cgaps)
