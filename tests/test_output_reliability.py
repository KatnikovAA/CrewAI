"""Regressions for calculator projection and JSON transport; entirely offline."""
import json
import unittest
from unittest.mock import patch
import httpx
from test_tasks import trip_data, budget_data, itinerary_data
from travel_planner.models import TripInput, BudgetResult, ItineraryResult
from travel_planner.settings import Settings
from travel_planner.tasks import calculator_input
from travel_planner.llm import create_llm, create_trip_llm


class OutputReliabilityTests(unittest.TestCase):
    def test_unknown_expenses_are_excluded_not_replaced_by_zero(self):
        data = budget_data()
        data['expenses'][-1].update(amount=None, kind='unknown')
        data.update(known_total='0.30', complete=False)
        args = calculator_input(BudgetResult(**data), TripInput(**trip_data()))
        self.assertEqual(args['expenses'], [{'name': key, 'amount': '0.10'} for key in ('transport','lodging','food')])
        self.assertEqual(args['currency'], 'RUB')
        self.assertEqual(args['budget'], '100')

    def test_known_zero_preserved_and_all_unknown_has_only_subtotal_sentinel(self):
        data = budget_data()
        for item in data['expenses']:
            item.update(amount=None, kind='unknown')
        data.update(known_total='0', complete=False)
        trip = TripInput(**trip_data())
        args = calculator_input(BudgetResult(**data), trip)
        self.assertEqual([e['amount'] for e in args['expenses']], ['0'])
        data['expenses'][0].update(amount='0.00', kind='estimate')
        args = calculator_input(BudgetResult(**data), trip)
        self.assertEqual(args['expenses'], [{'name':'transport', 'amount':'0.00'}])

    def test_full_trip_keeps_tools_separate_from_json_mode(self):
        settings = Settings('openai','provider/model-id','offline-test-key','https://api.example.com/v1')
        llm = create_trip_llm(settings)
        captured = []
        def respond(transport, request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={'id':'test','object':'chat.completion','created':1,
                'model':settings.model,'choices':[{'index':0,'message':{'role':'assistant','content':'{"ok":true}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        with patch('crewai.llms.hooks.transport._HTTPTransport.handle_request', autospec=True, side_effect=respond):
                result = llm.call([{'role':'user','content':'Return JSON with ok=true'}],
                    tools=[{'type':'function','function':{'name':'trip_cost_calculator','description':'Calculate','parameters':{'type':'object','properties':{}}}}])
        self.assertTrue(json.loads(result)['ok'])
        self.assertEqual(len(captured), 1)
        self.assertNotIn('response_format', captured[0])
        self.assertEqual(captured[0]['model'], settings.model)
        self.assertIn('tools', captured[0])
        self.assertEqual(captured[0]['max_tokens'], 12000)
        self.assertIsNone(create_llm(settings).response_format)
        with patch('crewai.llms.hooks.transport._HTTPTransport.handle_request', autospec=True, side_effect=respond):
            result = llm.call([{'role':'user','content':'Return final JSON with ok=true'}])
        self.assertTrue(json.loads(result)['ok'])
        self.assertEqual(captured[1]['response_format'], {'type':'json_object'})
        self.assertNotIn('tools', captured[1])

    def test_request_rewrite_preserves_headers_messages_and_explicit_schema(self):
        from travel_planner.llm import _trip_request_format
        body={'model':'same', 'messages':[{'role':'user','content':'JSON: поездка'}],
              'tools':[{'type':'function','function':{'name':'calculator'}}],
              'tool_choice':'auto', 'response_format':{'type':'json_object'}}
        original=httpx.Request('POST','https://example.com/v1/chat/completions',
            headers={'Authorization':'Bearer offline-key','Content-Type':'application/json'},
            json=body,extensions={'timeout':{'read':60}})
        prepared=_trip_request_format(original)
        sent=json.loads(prepared.content)
        self.assertNotIn('response_format',sent)
        self.assertEqual(sent['tools'],body['tools'])
        self.assertEqual(sent['tool_choice'],'auto')
        self.assertEqual(sent['messages'],body['messages'])
        self.assertEqual(prepared.headers['authorization'],'Bearer offline-key')
        self.assertEqual(int(prepared.headers['content-length']),len(prepared.content))
        self.assertEqual(prepared.extensions,original.extensions)
        self.assertIn('response_format',json.loads(original.content))
        schema=httpx.Request('POST','https://example.com/',json={
            'messages':body['messages'],'response_format':{'type':'json_schema','json_schema':{'name':'final'}}})
        self.assertIs(_trip_request_format(schema),schema)

    def test_async_format_policy_chains_observer_and_does_not_swallow_limits(self):
        import asyncio
        from crewai.llms.hooks.base import BaseInterceptor
        from travel_planner.runner import LimitReached
        calls=[]
        class Observer(BaseInterceptor):
            def on_outbound(self, request):
                calls.append('sync-out')
                return request
            def on_inbound(self, response):
                calls.append('sync-in')
                return response
            async def aon_outbound(self, request):
                calls.append('async-out')
                return request
            async def aon_inbound(self, response):
                calls.append('async-in')
                return response
        settings=Settings('openai','provider/model-id','offline','https://api.example.com/v1')
        llm=create_trip_llm(settings,interceptor=Observer())
        request=httpx.Request('POST','https://example.com/',json={'messages':[], 'tools':[{'type':'function'}], 'response_format':{'type':'json_object'}})
        wrapped=llm.interceptor
        self.assertNotIn('response_format',json.loads(wrapped.on_outbound(request).content))
        self.assertNotIn('response_format',json.loads(asyncio.run(wrapped.aon_outbound(request)).content))
        final=httpx.Request('POST','https://example.com/',json={'messages':[]})
        self.assertEqual(json.loads(asyncio.run(wrapped.aon_outbound(final)).content)['response_format'],{'type':'json_object'})
        response=httpx.Response(200)
        self.assertIs(wrapped.on_inbound(response),response)
        self.assertIs(asyncio.run(wrapped.aon_inbound(response)),response)
        self.assertEqual(calls,['sync-out','async-out','async-out','sync-in','async-in'])
        observer=Observer()
        def stop(request): raise LimitReached()
        observer.on_outbound=stop
        limited=create_trip_llm(settings,interceptor=observer)
        with self.assertRaises(LimitReached): limited.interceptor.on_outbound(request)

    def test_planner_receives_exact_tool_input_from_completed_budget(self):
        from crewai import Agent
        from test_tasks import research_data
        from travel_planner.crew import create_crew
        settings = Settings('openai','provider/model-id','offline','https://api.example.com/v1')
        crew = create_crew(TripInput(**trip_data()), llm=create_trip_llm(settings))
        costs = budget_data()
        costs['expenses'][-1].update(amount=None, kind='unknown')
        costs.update(known_total='0.30', complete=False)
        route=itinerary_data(); route.update(known_total='0.30', complete=False, budget_status='undetermined')
        fixtures=iter([research_data(),costs,route])
        def execute(agent, task, context=None, tools=None):
            if task.name=='itinerary':
                line=next(line for line in task.expected_output.splitlines() if line.startswith('calculator_input='))
                self.assertEqual(json.loads(line.split('=',1)[1]), calculator_input(BudgetResult(**costs),TripInput(**trip_data())))
            return json.dumps(next(fixtures))
        with patch.object(Agent,'execute_task',execute), patch('httpx.Client.send',side_effect=AssertionError('No HTTP')):
            output=crew.kickoff()
        self.assertEqual(output.pydantic.known_total, BudgetResult(**costs).known_total)

    def test_evidence_still_rejects_fabricated_zero_for_unknown(self):
        from types import SimpleNamespace
        from travel_planner.runner import verify_execution
        costs=budget_data(); costs['expenses'][-1].update(amount=None,kind='unknown')
        costs.update(known_total='0.30',complete=False)
        results=[SimpleNamespace(pydantic=None),SimpleNamespace(pydantic=BudgetResult(**costs)),SimpleNamespace(pydantic=None)]
        crew=SimpleNamespace(tasks=[SimpleNamespace(output=value,guardrail=lambda _: (True,None)) for value in results])
        records=[dict(type=kind,task=key) for kind in ('task_started','task_completed') for key in ('research','budget','itinerary')]
        records += [dict(type='llm_request',task=key,context_received={dep:True for dep in deps}) for key,deps in [('budget',['research']),('itinerary',['research','budget'])]]
        base=dict(type='tool_completed',status='ok',from_cache=False)
        records += [dict(base,task='research',tool='internet_search',urls=['https://example.com/']),dict(base,task='research',tool='website_reader',requested_url='https://example.com/',text_length=1)]
        for key in ('budget','itinerary'):
            records.append(dict(base,task=key,tool='trip_cost_calculator',currency='RUB',total='0.30',budget='100',amounts=['0.10']*3))
        self.assertTrue(verify_execution(crew,SimpleNamespace(tasks_output=results),records,TripInput(**trip_data()))['calculator_amounts'])
        records[-1]['amounts'].append('0')
        with self.assertRaisesRegex(ValueError,'Calculator input/output mismatch'):
            verify_execution(crew,SimpleNamespace(tasks_output=results),records,TripInput(**trip_data()))

    def test_json_mode_does_not_relax_schema_or_money(self):
        for raw in ['{"days":', 'not JSON']:
            with self.assertRaises(ValueError): ItineraryResult.model_validate_json(raw)
        data=itinerary_data(); data['known_total']=.4
        with self.assertRaises(ValueError): ItineraryResult.model_validate(data)
        data=itinerary_data(); data['unexpected']='ignored?'
        with self.assertRaises(ValueError): ItineraryResult.model_validate(data)


if __name__ == '__main__':
    unittest.main()
