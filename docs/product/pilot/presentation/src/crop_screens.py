"""Cut slide-sized fragments out of the target VM screenshots of 22.10.2026.

Sources are the unmodified acceptance screenshots in
docs/agent-graph-demo/deployments/2026-10-22/ (bytes fixed in files-sha256.txt).
Only cropping is applied: no retouching, no text edits.

Run from the repository root:
    python docs/product/pilot/presentation/src/crop_screens.py
"""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "docs/agent-graph-demo/deployments/2026-10-22"
OUT = Path(__file__).resolve().parent / "img"

# name: (source file, (left, top, right, bottom)) in source pixels
CROPS = {
    "b-impact": ("target-desktop-B.png", (430, 690, 990, 1010)),
    "b-basis": ("target-desktop-B.png", (994, 690, 1410, 970)),
    # The result boxes only. The line above them in the VM build calls the
    # operator run "independent"; the integration audit (F2) found that wrong,
    # so it is cropped out instead of being repeated on a slide.
    "b-check": ("target-desktop-B.png", (446, 1138, 974, 1296)),
    "e-list": ("target-desktop-E-confirmed.png", (30, 922, 426, 1262)),
    "e-check": ("target-desktop-E-confirmed.png", (446, 996, 974, 1188)),
    "a-summary": ("target-ready-A.png", (36, 248, 520, 322)),
    "a-nocheck": ("target-ready-A.png", (442, 930, 880, 958)),
    "stop-summary": ("target-provider-stop-unknown.png", (36, 248, 640, 322)),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, (src, box) in CROPS.items():
        img = Image.open(SRC / src).convert("RGB").crop(box)
        img.save(OUT / f"{name}.png", optimize=True)
        sizes[name] = list(img.size)
        print(name, box)
    # build.js sizes each picture from its pixel width
    (Path(__file__).resolve().parent / "img-sizes.json").write_text(
        json.dumps(sizes, indent=1) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
