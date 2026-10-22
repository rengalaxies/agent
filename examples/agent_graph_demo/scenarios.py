"""Fixed source versions; no dependency map and no importing analyzed source."""

from pathlib import Path

ROOT = Path(__file__).parent
REPOSITORIES = {
    "orders": "Orders",
    "status": "Status",
    "reporting": "Reporting",
    "billing": "Billing",
    "health": "Health",
    "export": "Export",
}
REQUIREMENT = (
    "Reporting requires the complete Orders collection, not only the first page.\n"
)


def sources(version):
    if version not in ("A", "B", "D", "E"):
        raise ValueError("unknown_version")
    result = {}
    for group in ("services", "consumers"):
        for f in sorted((ROOT / group).glob("*/*.py")):
            result[f"{f.parent.name}/{f.name}"] = f.read_text()
    if version != "A":
        result["orders/app.py"] = result["orders/app.py"].replace(
            "page_size: int | None = None", "page_size: int | None = 100"
        )
    if version in ("D", "E"):
        result["reporting/client.py"] = result["billing/client.py"]
    if version == "E":
        result["export/client.py"] = result["billing/client.py"]
    result["reporting/requirement.md"] = REQUIREMENT
    return result


def build_version(destination, version):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    expected = sources(version)
    for old in destination.rglob("*"):
        if old.is_file() and str(old.relative_to(destination)) not in expected:
            old.unlink()
    for name, text in expected.items():
        f = destination / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
