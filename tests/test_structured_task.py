"""A malformed model answer must reach our guardrail, including on a retry."""
import json
import unittest
from unittest.mock import patch
import test_crew
from test_tasks import research_data, budget_data, itinerary_data

class StructuredTaskTests(unittest.TestCase):
    def test_research_validation_error_is_repaired_without_converter_crash(self):
        from crewai import Agent
        crew=test_crew.CrewTests().factory(); seen=[]; feedback=[]
        def execute(agent,task,context=None,tools=None):
            seen.append(task.name)
            if task.name=='research':
                data=research_data()
                if seen.count('research')==1: data['places'][0]['price']['text']='unexpected'
                else: feedback.append(context)
            elif task.name=='budget': data=budget_data()
            else: data=itinerary_data()
            return json.dumps(data)
        with patch.object(Agent,'execute_task',execute), patch('httpx.Client.send',side_effect=AssertionError('No hidden HTTP converter')):
            crew.kickoff()
        self.assertEqual(seen,['research','research','budget','itinerary'])
        self.assertIn('extra_forbidden',feedback[0])
        self.assertIn('price',feedback[0])

    def test_invalid_retry_stays_controlled_and_does_not_bypass_guardrail(self):
        from crewai import Agent
        crew=test_crew.CrewTests().factory(); seen=[]
        def execute(agent,task,context=None,tools=None):
            seen.append(task.name)
            data=research_data(); data['places'][0]['price']['text']='unexpected'
            return json.dumps(data)
        with patch.object(Agent,'execute_task',execute), patch('httpx.Client.send',side_effect=AssertionError('No hidden HTTP converter')):
            with self.assertRaisesRegex(Exception,'guardrail validation'):
                crew.kickoff()
        self.assertEqual(seen,['research','research'])

    def test_dependency_sources_are_preserved_without_llm_copying(self):
        from crewai import Agent
        crew=test_crew.CrewTests().factory()
        research=research_data();research['places'][0]['description'].update(text='From source',kind='fact',sources=['https://example.com/official'])
        route=itinerary_data();route['sources']=['https://example.com/additional']
        fixtures=iter([research,budget_data(),route])
        with patch.object(Agent,'execute_task',lambda *args,**kwargs: json.dumps(next(fixtures))), patch('httpx.Client.send',side_effect=AssertionError('No HTTP')):
            output=crew.kickoff()
        self.assertEqual(set(map(str,output.pydantic.sources)),{'https://example.com/official','https://example.com/additional'})
