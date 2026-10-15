import json
import os
import unittest
from unittest.mock import patch

from travel_planner.tools.search import BasicTavilyClient, InternetSearchTool


class SearchTests(unittest.TestCase):
    @patch.dict(os.environ, {"TAVILY_API_KEY": ""})
    def test_missing_key_does_not_search(self):
        with patch("travel_planner.tools.search.TavilySearchTool") as backend:
            result = InternetSearchTool().run(search_query="Kazan")
            self.assertEqual(result["error_code"], "missing_key")
            backend.assert_not_called()

    @patch.dict(os.environ, {"TAVILY_API_KEY": "test-only"})
    @patch("travel_planner.tools.search.TavilySearchTool")
    def test_results_empty_and_failure_are_distinct(self, backend):
        backend.return_value.run.return_value = json.dumps({"results": [{"title": "City", "url": "https://example.com", "content": "Description"}]})
        tool = InternetSearchTool()
        result = tool.run(search_query="Kazan")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["results"][0], {"title": "City", "url": "https://example.com", "description": "Description"})
        backend.return_value.run.return_value = '{"results": []}'
        self.assertEqual(tool.run(search_query="Kazan")["status"], "empty")
        backend.return_value.run.side_effect = RuntimeError("test-only secret error")
        result = tool.run(search_query="Kazan")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("test-only", str(result))

    @patch("tavily.TavilyClient.search", return_value={"results": []})
    def test_basic_and_auto_parameters_cannot_be_overridden(self, search):
        BasicTavilyClient(api_key="test-only").search(query="City", search_depth="advanced", auto_parameters=True)
        self.assertEqual(search.call_args.kwargs["search_depth"], "basic")
        self.assertIs(search.call_args.kwargs["auto_parameters"], False)

    def test_invalid_query_or_advanced_argument(self):
        tool = InternetSearchTool()
        for data in [{"search_query": " "}, {"search_query": "City", "search_depth": "advanced"}]:
            with self.assertRaises(ValueError):
                tool.run(**data)
