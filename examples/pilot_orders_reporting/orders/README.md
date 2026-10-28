# Agent pilot: Orders

Isolated, author-written M2 acceptance data. No customer data or production use.
GET /orders accepts day and page_size (default 100) and returns 60 fixed order IDs.

Run: python -m uvicorn api:app --host 127.0.0.1 --port 8091
Install the dependencies listed in the delivery preparation report first.
Branches pilot-page-limit and pilot-restored form a fast-forward 100 → 20 → 100
sequence. pilot-docs-only changes only this file. No workflow or secret is needed.
