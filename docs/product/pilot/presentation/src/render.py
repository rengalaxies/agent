"""Export pilot-presentation.pptx to PDF and per-slide PNG with Microsoft PowerPoint.

PowerPoint renders the deck the way recipients will see it, so the PDF and the
review images come from the same engine. Windows only (COM automation, pywin32).

    python docs/product/pilot/presentation/src/render.py [png_dir]

png_dir defaults to ./renders next to this script and is not committed.
"""

import sys
from pathlib import Path

import win32com.client

HERE = Path(__file__).resolve().parent
DECK = HERE.parent / "pilot-presentation.pptx"
PDF = HERE.parent / "pilot-presentation.pdf"
PP_SAVE_AS_PDF = 32


def main() -> None:
    png_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "renders"
    png_dir.mkdir(parents=True, exist_ok=True)
    for old in png_dir.glob("slide-*.png"):
        old.unlink()

    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(DECK), ReadOnly=True, Untitled=False, WithWindow=False)
    try:
        pres.SaveAs(str(PDF), PP_SAVE_AS_PDF)
        for i, slide in enumerate(pres.Slides, start=1):
            slide.Export(str(png_dir / f"slide-{i:02d}.png"), "PNG", 1600, 900)
        print(f"{pres.Slides.Count} slides -> {PDF.name}, {png_dir}")
    finally:
        pres.Close()
        if app.Presentations.Count == 0:
            app.Quit()


if __name__ == "__main__":
    main()
