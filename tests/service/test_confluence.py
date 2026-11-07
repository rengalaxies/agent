import unittest
from unittest.mock import Mock
from agent_service.confluence import linked_pages, read_linked_pages
from agent_service.http import ClientError


class ConfluenceTest(unittest.TestCase):
    def description(self, url):
        return {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "requirements", "marks": [
                {"type": "link", "attrs": {"href": url}}]}]}]}

    def test_only_explicit_same_site_pages(self):
        url = "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"
        self.assertEqual(linked_pages(self.description(url), "pilot.atlassian.net"), ["123"])
        for bad in (url.replace("pilot.", "other."), url.replace("https:", "http:"),
                    url.replace("/pages/123", "/attachments/123/file.pdf")):
            self.assertEqual(linked_pages(self.description(bad), "pilot.atlassian.net"), [])

    def test_table_version_and_skipped_images_without_traversal(self):
        client = Mock()
        client.request.return_value.json.return_value = {
            "id": "123", "_links": {"base": "https://pilot.atlassian.net/wiki"}, "title": "Requirements", "version": {"number": 7},
            "body": {"storage": {"value": '<h2>Rules</h2><table><tr><td>R1</td><td>Keep API</td></tr></table><ac:image><ri:attachment ri:filename="secret.png"/></ac:image><a href="https://pilot.atlassian.net/wiki/spaces/OOP/pages/456">Other</a>'}}}
        [page] = read_linked_pages(client, self.description(
            "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"), "pilot.atlassian.net")
        self.assertEqual(page["version"], 7)
        self.assertIn("R1 | Keep API", page["text"])
        self.assertEqual(page["unsupported_blocks"], 1)
        self.assertNotIn("secret", page["text"])
        client.request.assert_called_once()

    def test_wrong_page_identity_is_refused(self):
        client = Mock()
        client.request.return_value.json.return_value = {"id": "999"}
        with self.assertRaisesRegex(ClientError, "confluence_identity_mismatch"):
            read_linked_pages(client, self.description(
                "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"), "pilot.atlassian.net")

    def test_removed_link_clears_old_documentation_without_fetch(self):
        from agent_service.confluence import with_documentation
        client = Mock()
        pages = read_linked_pages(client, {"type": "doc", "content": []}, "pilot.atlassian.net")
        old = {"sections": [{"title": "Analysis", "items": []},
                            {"title": "Связанная документация Confluence", "items": ["old secret text"]}]}
        updated = with_documentation(old, pages)
        self.assertNotIn("old secret text", str(updated))
        client.request.assert_not_called()

    def test_unavailable_page_is_explicit_without_previous_text(self):
        from agent_service.confluence import with_documentation
        from agent_service.http import AuthError, NotFound
        for error in (AuthError(status=403), NotFound(status=404)):
            client = Mock()
            client.request.side_effect = error
            pages = read_linked_pages(client, self.description(
                "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"), "pilot.atlassian.net")
            result = with_documentation({"sections": []}, pages)
            self.assertIn("UNAVAILABLE", str(result))
            self.assertIn("123", str(result))

    def test_next_read_uses_new_page_version(self):
        client = Mock()
        for version, text in ((1, "first requirement"), (2, "replacement requirement")):
            client.request.return_value.json.return_value = {
                "id": "123", "_links": {"base": "https://pilot.atlassian.net/wiki"}, "title": "Rules", "version": {"number": version},
                "body": {"storage": {"value": "<p>" + text + "</p>"}}}
            [page] = read_linked_pages(client, self.description(
                "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"), "pilot.atlassian.net")
            self.assertEqual((page["version"], page["text"]), (version, text))
        self.assertEqual(client.request.call_count, 2)


    def test_malformed_url_does_not_break_reconciliation(self):
        self.assertEqual(linked_pages(self.description("https://[broken"),
                                      "pilot.atlassian.net"), [])

    def test_void_tag_inside_skipped_block_does_not_hide_later_text(self):
        from agent_service.confluence import PageText
        parser = PageText()
        parser.feed('<ac:structured-macro><p>skip<br>inside</p></ac:structured-macro><p>visible</p>')
        self.assertEqual("".join(parser.parts).strip(), "visible")


    def test_page_from_other_cloud_site_is_refused(self):
        client = Mock()
        client.request.return_value.json.return_value = {
            "id": "123", "_links": {"base": "https://other.atlassian.net/wiki"}}
        with self.assertRaisesRegex(ClientError, "confluence_site_mismatch"):
            read_linked_pages(client, self.description(
                "https://pilot.atlassian.net/wiki/spaces/OOP/pages/123"), "pilot.atlassian.net")


    def test_self_closing_break_does_not_expose_skipped_macro(self):
        from agent_service.confluence import PageText
        for markup in (
                '<ac:structured-macro><br/>SECRET</ac:structured-macro><p>visible</p>',
                '<ac:structured-macro><p>skip<br/>SECRET</p>MORE SECRET</ac:structured-macro><p>visible</p>'):
            parser = PageText()
            parser.feed(markup)
            self.assertEqual("".join(parser.parts).strip(), "visible")
