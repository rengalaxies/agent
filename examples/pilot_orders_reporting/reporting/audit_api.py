"""A different service owns the same route: task scope must be explicit."""
from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def report_status():
    return {"status": "reporting-only"}
