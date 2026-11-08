"""Bounded text context from explicitly linked Confluence pages."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .http import AuthError, ClientError, NotFound

MAX_PAGES = 5
MAX_TEXT = 4000


def linked_pages(description, site):
    """Collect page IDs only from explicit ADF links on the configured site."""
    ids = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            urls = []
            if node.get("type") == "inlineCard":
                urls.append(node.get("attrs", {}).get("url", ""))
            if node.get("type") == "text":
                urls.extend(re.findall(r"https://[^\s<>]+", node.get("text", "")))
                urls.extend(mark.get("attrs", {}).get("href", "")
                            for mark in node.get("marks", []) if mark.get("type") == "link")
            for url in urls:
                try:
                    parsed = urlsplit(url)
                except ValueError:
                    continue
                if (parsed.scheme != "https" or parsed.netloc != site
                        or parsed.username or parsed.password):
                    continue
                match = re.fullmatch(r"/wiki/spaces/[^/]+/pages/([0-9]+)(?:/[^/]*)?/?", parsed.path)
                if match and match[1] not in ids:
                    ids.append(match[1])
            visit(node.get("content", []))

    visit(description)
    if len(ids) > MAX_PAGES:
        raise ClientError("confluence_page_limit")
    return ids


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag not in {"img", "br", "hr", "input", "meta", "link"}:
                self.depth += 1
        elif tag in {"ac:structured-macro", "ac:image", "script", "style"}:
            self.depth = 1
            self.skipped += 1
        elif tag == "img":
            self.skipped += 1
        elif tag in {"p", "div", "tr", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in {"img", "br", "hr", "input", "meta", "link"}:
            return
        if self.depth:
            self.depth -= 1
        elif tag in {"p", "div", "tr", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def read_linked_pages(client, description, site):
    """Client is pinned to the operator's Confluence gateway, never page URLs."""
    pages = []
    for page_id in linked_pages(description, site):
        try:
            response = client.request("GET", f"/wiki/api/v2/pages/{page_id}",
                                      query={"body-format": "storage"}).json()
        except (AuthError, NotFound) as exc:
            pages.append({
                "page_id": page_id,
                "url": f"https://{site}/wiki/pages/viewpage.action?pageId={page_id}",
                "status": "UNAVAILABLE",
                "reason": exc.code,
            })
            continue
        if str(response.get("id")) != page_id:
            raise ClientError("confluence_identity_mismatch")
        if response.get("_links", {}).get("base", "").rstrip("/") != f"https://{site}/wiki":
            raise ClientError("confluence_site_mismatch")
        parser = PageText()
        parser.feed(response["body"]["storage"]["value"])
        text = "".join(parser.parts).strip()
        pages.append({
            "page_id": page_id,
            "version": response["version"]["number"],
            "title": response["title"],
            "url": f"https://{site}/wiki/pages/viewpage.action?pageId={page_id}",
            "text": text[:MAX_TEXT],
            "truncated": len(text) > MAX_TEXT,
            "unsupported_blocks": parser.skipped,
        })
    return pages


def with_documentation(doc, pages):
    """Add attributed context without upgrading documentation to a code finding."""
    import copy
    result = copy.deepcopy(doc)
    title = "Связанная документация Confluence"
    result["sections"] = [section for section in result.get("sections", [])
                          if section.get("title") != title]
    items = []
    for page in pages:
        if page.get("status") == "UNAVAILABLE":
            items.append(f"Confluence UNAVAILABLE: {page['url']} ({page['reason']}). "
                         "Содержимое не использовано, требования этой страницы не проверены.")
            continue
        items.append(f"Confluence {page['title']} — версия {page['version']}, {page['url']}")
        items.append("Документированные требования; соответствие коду отдельно не подтверждено.")
        # Keep the bounded extraction intact so table cells retain their surrounding context.
        items.append(page["text"])
        if page["truncated"] or page["unsupported_blocks"]:
            items.append(f"Ограничения чтения: обрезка={page['truncated']}, "
                         f"пропущено неподдерживаемых блоков={page['unsupported_blocks']}.")
    if items:
        result.setdefault("sections", []).append({"title": "Связанная документация Confluence", "items": items})
    if "jira_summary" in doc:
        from .jira_presentation import documentation_summary
        result["jira_summary"] = documentation_summary(doc["jira_summary"], pages)
    return result
