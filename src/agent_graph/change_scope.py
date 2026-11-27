"""Conservative comparison bases for default-only exemptions, never execution."""
from __future__ import annotations

import ast
import copy

from .contracts import digest


def handler_without_page_default(fn):
    node = copy.deepcopy(fn)
    args = node.args.posonlyargs + node.args.args
    for index, arg in enumerate(args[len(args) - len(node.args.defaults):]):
        if arg.arg == "page_size":
            node.args.defaults[index] = ast.Constant(value="EXCLUDED_PAGE_SIZE_DEFAULT")
    for index, arg in enumerate(node.args.kwonlyargs):
        if arg.arg == "page_size" and node.args.kw_defaults[index] is not None:
            node.args.kw_defaults[index] = ast.Constant(value="EXCLUDED_PAGE_SIZE_DEFAULT")
    return digest(ast.dump(node, include_attributes=False))


def contract_without_page_default(path_item, method, document):
    # References and inherited contract settings can live outside paths. Do not
    # resolve them or silently exclude their changes from the exemption proof.
    basis = copy.deepcopy([path_item, {k: v for k, v in document.items() if k != "paths"}])
    for parameters in (basis[0].get("parameters", []), basis[0][method].get("parameters", [])):
        if isinstance(parameters, list):
            for parameter in parameters:
                if (isinstance(parameter, dict) and parameter.get("name") == "page_size"
                        and parameter.get("in") == "query" and isinstance(parameter.get("schema"), dict)):
                    parameter["schema"].pop("default", None)
    return digest(basis)


def scalar_query_annotation(node, bindings):
    """Only unshadowed primitive annotations establish FastAPI query binding.

    Annotated/Body/Query aliases, containers and forward references are opaque.
    This is intentionally a closed grammar, not an evaluator of annotations.
    """
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"int", "float", "str", "bool"} and not bindings[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        def scalar_or_none(value):
            return (isinstance(value, ast.Constant) and value.value is None
                    or scalar_query_annotation(value, bindings))
        return scalar_or_none(node.left) and scalar_or_none(node.right)
    return False


def opaque_provider_basis(context, repositories):
    """Python outside recognised handlers, scoped to already known providers.

    No helper resolution is attempted. A changed basis means possible untracked
    semantics, not proof that a helper executes or affects a specific operation.
    Comments/line positions are ignored; missing/unparseable files stay covered
    by collection/extraction gaps as well as this conservative comparison.
    """
    handlers = {}
    for operation in context["graph"]["operations"]:
        for citation in operation["evidence"]:
            handlers.setdefault(citation["source_id"], set()).add(citation["start_line"])
    basis = {repo: [] for repo in repositories}
    for source in context["sources"].values():
        repo = source["repository"]
        if repo not in basis or not source["path"].endswith(".py"):
            continue
        try:
            tree = ast.parse(source["text"])
        except (SyntaxError, ValueError, RecursionError):
            basis[repo].append((source["path"], source["sha256"]))
            continue
        tree.body = [n for n in tree.body if not (
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.lineno in handlers.get(source["id"], set()))]
        if tree.body:
            basis[repo].append((source["path"], digest(ast.dump(tree, include_attributes=False))))
    return {repo: sorted(items) for repo, items in basis.items()}
