from pathlib import Path
import re
import unittest


PAGE = Path(__file__).resolve().parents[2] / "src/change_completion/web/index.html"


class ProductUIAssetTest(unittest.TestCase):
    def test_self_contained_and_no_persistent_credentials(self):
        page = PAGE.read_text()
        self.assertIn('lang="ru"', page)
        self.assertIn('type="password"', page)
        self.assertNotRegex(page, r'(?:src|href)=["\']https?://')
        self.assertNotRegex(page, r'\b(?:localStorage|sessionStorage)\b|document\.cookie')

    def test_dynamic_content_is_text_only(self):
        page = PAGE.read_text()
        script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
        self.assertNotRegex(script, r'innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(')
        self.assertIn("textContent", script)
        self.assertIn("encodeURIComponent", script)


if __name__ == "__main__":
    unittest.main()
