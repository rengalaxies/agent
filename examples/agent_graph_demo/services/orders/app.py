"""Executable synthetic Orders API. Dataset is operator supplied, outside the corpus."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI()


@app.get("/orders")
def orders(page_size: int | None = None, cursor: int = 0):
    items = json.loads(Path(os.environ["DEMO_DATASET"]).read_text())
    if cursor < 0 or cursor > len(items) or page_size is not None and page_size < 1:
        raise HTTPException(422, "invalid_page")
    stop = len(items) if page_size is None else min(cursor + page_size, len(items))
    return {
        "items": items[cursor:stop],
        "next_cursor": stop if stop < len(items) else None,
    }
