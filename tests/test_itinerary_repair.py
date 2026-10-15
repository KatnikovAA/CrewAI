"""Offline repair of the observed itinerary schema violations."""
import json
import unittest
from unittest.mock import patch
import test_crew
from test_tasks import research_data, budget_data, itinerary_data

class ItineraryRepairTests(unittest.TestCase):
    def scenario(self, repair):
        from crewai import Agent
        crew = test_crew.CrewTests().factory()
        calls, feedback = [], []
        def execute(agent, task, context=None, tools=None):
            calls.append(task.name)
            if task.name == 'research': return json.dumps(research_data())
            if task.name == 'budget': return json.dumps(budget_data())
            feedback.append(context or '')
            data = itinerary_data()
            if not repair or calls.count('itinerary') == 1:
                data['days'][0]['\u0000'] = 'bad'
                data['days'][1]['schedule'].update(text='Proposed visit', kind='unknown')
            return json.dumps(data)
        with patch.object(Agent, 'execute_task', execute), patch('httpx.Client.send', side_effect=AssertionError('No HTTP')):
            if repair: crew.kickoff()
            else:
                with self.assertRaises(Exception): crew.kickoff()
        return calls, feedback

    def test_repairs_exact_fields_before_completion(self):
        calls, feedback = self.scenario(True)
        self.assertEqual(calls, ['research','budget','itinerary','itinerary'])
        self.assertIn('extra_forbidden', feedback[1])
        self.assertIn('schedule', feedback[1])
        self.assertIn('unknown', feedback[1])

    def test_only_one_repair_when_invalid(self):
        calls, _ = self.scenario(False)
        self.assertEqual(calls.count('itinerary'), 2)
