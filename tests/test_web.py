import unittest
from unittest.mock import patch

import requests

from travel_planner.tools.web import WebsiteReaderTool


class ReaderTests(unittest.TestCase):
    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            WebsiteReaderTool().run(website_url="file:///secret")

    @patch("travel_planner.tools.web.safe_get_bounded")
    def test_source_text_and_removal_of_scripts(self, fetch):
        fetch.return_value = (b"<html><script>secretScript</script><p>Hello</p></html>", "text/html", "https://example.com/final")
        result = WebsiteReaderTool().run(website_url="https://example.com")
        self.assertEqual(result["text"], "Hello")
        self.assertEqual(result["source_url"], "https://example.com/final")
        self.assertEqual(result["status"], "ok")

    @patch("travel_planner.tools.web.safe_get_bounded")
    def test_empty_page_is_not_network_error(self, fetch):
        fetch.return_value = (b"<html><script>x</script></html>", "text/html", "https://example.com")
        self.assertEqual(WebsiteReaderTool().run(website_url="https://example.com")["status"], "empty")
        fetch.side_effect = requests.ConnectionError("raw error must stay hidden")
        result = WebsiteReaderTool().run(website_url="https://example.com")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("raw error", str(result))

    @patch("travel_planner.tools.web.safe_get_bounded")
    def test_http_error_and_non_html(self, fetch):
        fetch.side_effect = requests.HTTPError(response=type("Response", (), {"status_code": 404})())
        self.assertEqual(WebsiteReaderTool().run(website_url="https://example.com")["error_code"], "http_404")
        fetch.side_effect = None
        fetch.return_value = (b"%PDF", "application/pdf", "https://example.com")
        self.assertEqual(WebsiteReaderTool().run(website_url="https://example.com")["error_code"], "unsupported_content")

    @patch("travel_planner.tools.web.safe_get_bounded")
    def test_long_page_is_bounded_and_truncation_explicit(self, fetch):
        fetch.return_value = (b'<html><main>'+b'A'*20000+b'</main></html>', 'text/html', 'https://example.com')
        result = WebsiteReaderTool(max_text_chars=6000).run(website_url='https://example.com')
        self.assertEqual(len(result['text']),6000)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['original_text_chars'],20000)
