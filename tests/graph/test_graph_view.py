"""The human view: impact path, origin and freshness on one page, filtered by grants."""
from agent_graph.engine import Graph
from agent_graph.graph_query import GraphQuery
from agent_graph.graph_store import OwnershipMapping
from agent_graph.graph_view import basis_text, make_app, render_html
from tests.graph.test_graph_store import StandCase


class ViewTests(StandCase):
    def setUp(self):
        super().setUp()
        store, self.gs = self.open()
        graph = Graph(self.policy(), store)
        self.gs.sync_code(self.context(graph))
        self.gs.sync_code(self.context(graph, orders="pr-7"))
        self.gs.sync_ownership("acme", "prod", OwnershipMapping(
            source="installation_mapping", version="ownership-1",
            services=dict(orders="team-orders", reporting="team-reporting")))

    def test_page_shows_path_origin_freshness_owner_and_history(self):
        page = render_html(GraphQuery.for_policy(self.gs, self.policy()), environments=["prod", "stage"])
        self.assertIn("reporting -&gt; orders GET /orders", page)
        self.assertIn("reporting/client.py:7 (load_day) @", page)
        self.assertIn("team-reporting", page)
        # archive, audit and billing have no mapping: the page says so instead of guessing.
        self.assertEqual(page.count("команда не определена"), 3)
        self.assertIn("код: закрыто в версии 2, фрагмент изменился", page)
        self.assertIn("свежее", page)
        self.assertIn("orders GET /orders", page)
        self.assertIn('href="?environment=stage"', page)
        self.assertNotIn("<script", page)

    def test_revoked_repository_is_not_on_the_page(self):
        page = render_html(GraphQuery.for_policy(self.gs, self.policy(["orders", "billing", "audit", "archive"])))
        self.assertNotIn("reporting", page)
        self.assertIn("archive -&gt; orders GET /orders", page)

    def test_values_from_sources_are_escaped_and_links_need_an_http_template(self):
        basis = dict(origin="code", repository="orders", path='api.py"><script>alert(1)</script>',
                     start_line=3, commit="a" * 40, callsite={"symbol": "<b>x</b>"})
        text = basis_text(basis, {"orders": "javascript:alert(1)"})
        self.assertNotIn("<script>", text)
        self.assertNotIn("<b>x</b>", text)
        self.assertNotIn("href", text)
        linked = basis_text(basis, {"orders": "https://git.example/{repository}/blob/{commit}/{path}#L{line}"})
        self.assertIn('href="https://git.example/orders/blob/' + "a" * 40, linked)
        self.assertNotIn("<script>", linked)

    def test_wsgi_app_is_read_only_uncached_and_filters_environment(self):
        app = make_app(lambda env: GraphQuery.for_policy(self.gs, self.policy()), ["prod"])
        def call(method="GET", query="", path="/"):
            seen = {}
            body = b"".join(app(dict(REQUEST_METHOD=method, QUERY_STRING=query, PATH_INFO=path),
                                lambda status, headers: seen.update(status=status, headers=dict(headers))))
            return seen["status"], seen["headers"], body
        status, headers, body = call(query="environment=prod")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("reporting".encode(), body)
        self.assertEqual(call(query="environment=stage")[0], "404 Not Found")
        self.assertEqual(call(method="POST")[0], "405 Method Not Allowed")
        self.assertEqual(call(path="/admin")[0], "404 Not Found")
