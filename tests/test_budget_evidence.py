"""Regression: budget must recalculate before itinerary starts; no network."""
import json
import unittest
from unittest.mock import patch
import test_crew
from test_tasks import research_data, budget_data, itinerary_data, trip_data
from travel_planner.models import TripInput


class BudgetEvidenceTests(unittest.TestCase):
    def run_scenario(self, repair):
        from crewai import Agent
        from travel_planner.runner import install_budget_evidence_guard
        crew = test_crew.CrewTests().factory()
        records, calls, feedback = [], [], []
        install_budget_evidence_guard(crew.tasks[1], records, TripInput(**trip_data()), lambda: True)
        def execute(agent, task, context=None, tools=None):
            calls.append(task.name)
            if task.name == 'research':
                return json.dumps(research_data())
            if task.name == 'budget':
                feedback.append(context or '')
                if calls.count('budget') == 2 and repair:
                    records.append(dict(type='tool_completed', task='budget', tool='trip_cost_calculator',
                        status='ok', from_cache=False, currency='RUB', total='0.40', budget='100',
                        amounts=['0.10']*4))
                else:
                    records.append(dict(type='tool_completed', task='budget', tool='trip_cost_calculator',
                        status='ok', from_cache=False, currency='RUB', total='0.50', budget='100',
                        amounts=['0.10']*3+['0.20']))
                return json.dumps(budget_data())
            return json.dumps(itinerary_data())
        with patch.object(Agent, 'execute_task', execute), patch('httpx.Client.send', side_effect=AssertionError('No HTTP')):
            if repair:
                crew.kickoff()
            else:
                with self.assertRaises(Exception):
                    crew.kickoff()
        return calls, feedback

    def test_recalculates_before_itinerary_with_exact_feedback(self):
        calls, feedback = self.run_scenario(True)
        self.assertEqual(calls, ['research', 'budget', 'budget', 'itinerary'])
        self.assertIn('trip_cost_calculator', feedback[1])
        self.assertIn('"amount": "0.10"', feedback[1])

    def test_stops_after_one_failed_repair_without_itinerary(self):
        calls, _ = self.run_scenario(False)
        self.assertEqual(calls, ['research', 'budget', 'budget'])
