"""Без сети: фабрики обязаны сохранять модель и ограничения."""
import unittest
from unittest.mock import patch


class AgentFactoryTests(unittest.TestCase):
    def test_agents_without_network(self):
        from travel_planner.settings import Settings
        with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            from travel_planner.agents import create_agents
            from travel_planner.llm import create_llm
            llm = create_llm(Settings("openai", "deepseek/deepseek-v4.1-flash", "local-test", "https://polza.ai/api/v1"))
            agents = create_agents(llm=llm)
        expected = {"researcher": {"internet_search", "website_reader"},
                    "budget": {"internet_search", "website_reader", "trip_cost_calculator"},
                    "planner": {"trip_cost_calculator"}}
        self.assertEqual(set(agents), set(expected))
        for name, agent in agents.items():
            self.assertEqual({tool.name for tool in agent.tools}, expected[name])
            self.assertIs(agent.llm, llm)
            self.assertIs(agent.function_calling_llm, llm)
            self.assertFalse(agent.allow_delegation)
            self.assertFalse(agent.allow_code_execution)
            self.assertFalse(agent.cache)
            self.assertFalse(agent.reasoning)
            self.assertFalse(agent.knowledge_sources)
            self.assertIsNone(agent.memory)
            self.assertEqual(agent.max_retry_limit, 0)
            self.assertLessEqual(agent.max_iter, 6)
            self.assertEqual(agent.max_execution_time, 240 if name == "researcher" else 180)
            self.assertIn("данные", agent.backstory)
        self.assertEqual(llm.model, "deepseek/deepseek-v4.1-flash")

    def test_missing_settings_rejected(self):
        from travel_planner.llm import create_llm
        from travel_planner.settings import Settings
        with self.assertRaises(ValueError):
            create_llm(Settings("", "", ""))
