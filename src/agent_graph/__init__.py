"""Advisory, offline HTTP evidence graph. Independent of research release gates."""

# Revision 6 also invalidates explicit setattr/delattr mutation of positive bindings.
# Saved v4/v5 contexts and knowledge require revalidation; schemas are unchanged.
PROFILE = "http-requests-6"
SCHEMA = "agent-graph-1"


def core_identity():
    """What a caller can check about the core it actually loaded, without trusting a SHA string.

    Line endings are normalized so a Windows checkout and a Linux image of the same
    commit have the same digest.
    """
    import hashlib
    from pathlib import Path
    from .output_contracts import SCHEMA_VERSION
    root = Path(__file__).resolve().parent
    files = sorted((p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
                   for p in root.rglob("*.py"))
    return dict(profile=PROFILE, schema=SCHEMA, output_schema_version=SCHEMA_VERSION,
                core_digest=hashlib.sha256(repr(files).encode()).hexdigest())
