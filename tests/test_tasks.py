"""Offline contracts; these fixtures are not model responses."""
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from travel_planner.models import TripInput, ResearchResult, BudgetResult, ItineraryResult


def trip_data(**changes):
    return dict(departure_city="Москва", destination="Казань", start_date="2026-11-01",
                end_date="2026-11-02", budget="100", currency="RUB", travelers=2,
                interests=["музеи"], **changes)


def finding():
    return dict(text=None, kind="unknown", sources=[], note="Нет сведений")


def research_data():
    return dict(places=[dict(id="p1", name="Музей", description=finding(),
                            conditions=finding(), hours=finding(), price=dict(
                                amount=None, currency=None, kind="unknown", sources=[], note="Нет цены"))],
                uncertainties=["Требуется уточнение"])


def budget_data():
    return dict(currency="RUB", expenses=[dict(id=k, category=k, name=k, amount="0.10",
                kind="estimate", sources=[], note="Учебное допущение", place_ids=["p1"] if k == "activities" else [])
                for k in ["transport", "lodging", "food", "activities"]],
                known_total="0.40", complete=True, logistics=[finding()], assumptions=["Учебные суммы"])


def itinerary_data():
    return dict(days=[dict(date=f"2026-11-0{i}", place_ids=["p1"] if i == 1 else [],
                          schedule=finding(), movements=finding()) for i in (1, 2)],
                currency="RUB", known_total="0.40", complete=True, budget_status="remaining", over_budget="0",
                sources=[], caveats=["Расходы оценочные"])


class SchemaTests(unittest.TestCase):
    def test_trip_days_and_money(self):
        trip = TripInput(**trip_data())
        self.assertEqual(trip.days, 2)
        self.assertEqual(trip.budget, Decimal("100"))
        data = trip_data(); data["end_date"] = data["start_date"]
        self.assertEqual(TripInput(**data).days, 1)

    def test_invalid_trip(self):
        for key, values in {"end_date": ["2026-10-31", "bad"], "travelers": [0, -1, True, 1.5],
                            "budget": [True, 0.1, "-1", "NaN", "Infinity", "1e101", "1e-31"],
                            "currency": ["", "rub", "R"], "departure_city": [" "]}.items():
            for value in values:
                data = trip_data(); data[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    TripInput(**data)

    def test_unknown_and_fact_evidence(self):
        ResearchResult(**research_data())
        data = research_data(); data["places"][0]["hours"]["kind"] = "fact"
        with self.assertRaises(ValueError): ResearchResult(**data)
        data = research_data(); data["places"][0]["price"]["amount"] = "10"
        with self.assertRaises(ValueError): ResearchResult(**data)

    def test_money_and_totals(self):
        result = BudgetResult(**budget_data())
        self.assertIsInstance(result.known_total, Decimal)
        self.assertEqual(json.loads(result.model_dump_json())["known_total"], "0.40")
        data = budget_data(); data["known_total"] = "0.41"
        with self.assertRaises(ValueError): BudgetResult(**data)
        data = budget_data(); data["expenses"][0].update(amount=None, kind="unknown")
        data.update(known_total="0.30", complete=False)
        BudgetResult(**data)
        data["complete"] = True
        with self.assertRaises(ValueError): BudgetResult(**data)

    def test_dates_and_unique_ids(self):
        data = itinerary_data(); data["days"][1]["date"] = "2026-11-04"
        with self.assertRaises(ValueError): ItineraryResult(**data)
        data = budget_data(); data["expenses"][1]["id"] = "transport"
        with self.assertRaises(ValueError): BudgetResult(**data)

    def test_output_money_and_exact_large_sum(self):
        for invalid in [True, 0.1, "-1", "NaN", "Infinity", "1e101", "1e-31"]:
            data = budget_data(); data["expenses"][0]["amount"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): BudgetResult(**data)
        data = budget_data()
        data["expenses"][0]["amount"] = "123456789012345678901234567890.0000000001"
        data["known_total"] = "123456789012345678901234567890.3000000001"
        result = BudgetResult(**data)
        self.assertEqual(json.loads(result.model_dump_json())["known_total"], data["known_total"])
        data = budget_data(); data["expenses"][0]["amount"] = "1e-7"
        data["known_total"] = "0.3000001"
        self.assertEqual(json.loads(BudgetResult(**data).model_dump_json())["expenses"][0]["amount"], "0.0000001")


class TaskTests(unittest.TestCase):
    def setUp(self):
        from travel_planner.agents import create_agents
        from travel_planner.llm import create_llm
        from travel_planner.settings import Settings
        from travel_planner.tasks import create_tasks
        self.trip = TripInput(**trip_data())
        with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            llm = create_llm(Settings("openai", "deepseek/deepseek-v4.1-flash", "test", "https://polza.ai/api/v1"))
            self.agents = create_agents(llm=llm)
            self.tasks = create_tasks(self.trip, self.agents)

    def output(self, key, model, data):
        from crewai.tasks.task_output import TaskOutput
        return TaskOutput(description="fixture", raw=json.dumps(data), pydantic=model(**data), agent=key)

    def test_identity_dag_and_schemas(self):
        tasks = self.tasks
        self.assertEqual(list(tasks), ["research", "budget", "itinerary"])
        for key, agent, schema in [("research", "researcher", ResearchResult), ("budget", "budget", BudgetResult),
                                   ("itinerary", "planner", ItineraryResult)]:
            task = tasks[key]
            self.assertIs(task.agent, self.agents[agent])
            self.assertIs(task.output_pydantic, schema)
            self.assertEqual(task.guardrail_max_retries, 1 if key in ("research", "itinerary") else 0)
            self.assertTrue(task.description and task.expected_output)
            schema.model_json_schema()
        self.assertEqual(tasks["research"].context, [])
        self.assertIs(tasks["budget"].context[0], tasks["research"])
        self.assertIs(tasks["itinerary"].context[0], tasks["research"])
        self.assertIs(tasks["itinerary"].context[1], tasks["budget"])

    def test_guardrails_cross_task_contracts(self):
        tasks = self.tasks
        research = self.output("research", ResearchResult, research_data())
        self.assertTrue(tasks["research"].guardrail(research)[0])
        tasks["research"].output = research
        budget = self.output("budget", BudgetResult, budget_data())
        self.assertTrue(tasks["budget"].guardrail(budget)[0])
        tasks["budget"].output = budget
        route = self.output("itinerary", ItineraryResult, itinerary_data())
        self.assertTrue(tasks["itinerary"].guardrail(route)[0])
        data = itinerary_data(); data["known_total"] = "0.10"
        self.assertFalse(tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, data))[0])
        data = itinerary_data(); data["days"][0]["place_ids"] = ["invented"]
        self.assertFalse(tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, data))[0])

    def test_raw_invalid_and_absent_context_rejected(self):
        from crewai.tasks.task_output import TaskOutput
        bad = TaskOutput(description="fixture", raw="{}", agent="researcher")
        self.assertFalse(self.tasks["research"].guardrail(bad)[0])
        self.assertFalse(self.tasks["budget"].guardrail(self.output("budget", BudgetResult, budget_data()))[0])

    def test_wrong_currency_references_and_dates(self):
        self.tasks["research"].output = self.output("research", ResearchResult, research_data())
        for change in ("currency", "reference"):
            data = budget_data()
            if change == "currency": data["currency"] = "USD"
            else: data["expenses"][-1]["place_ids"] = ["missing"]
            self.assertFalse(self.tasks["budget"].guardrail(self.output("budget", BudgetResult, data))[0])
        self.tasks["budget"].output = self.output("budget", BudgetResult, budget_data())
        data = itinerary_data(); data["days"] = data["days"][:1]
        self.assertFalse(self.tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, data))[0])

    def test_incomplete_and_exceeded_budget(self):
        self.tasks["research"].output = self.output("research", ResearchResult, research_data())
        for amount, total, status, over in [(None, "0.30", "undetermined", "0"),
                                            ("101", "101.30", "exceeded", "1.30")]:
            data = budget_data()
            data["expenses"][0].update(amount=amount, kind="unknown" if amount is None else "estimate")
            data.update(known_total=total, complete=False)
            budget = self.output("budget", BudgetResult, data)
            self.assertTrue(self.tasks["budget"].guardrail(budget)[0])
            self.tasks["budget"].output = budget
            route = itinerary_data()
            route.update(known_total=total, complete=False, budget_status=status, over_budget=over)
            self.assertTrue(self.tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, route))[0])
            route["budget_status"] = "remaining"
            self.assertFalse(self.tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, route))[0])

    def test_sources_and_raw_valid_json(self):
        from crewai.tasks.task_output import TaskOutput
        data = research_data()
        data["places"][0]["description"].update(text="Из источника", kind="fact", sources=["https://example.com/"])
        raw = TaskOutput(description="fixture", raw=json.dumps(data), agent="researcher")
        self.assertTrue(self.tasks["research"].guardrail(raw)[0])
        self.assertIsInstance(raw.pydantic, ResearchResult)
        self.tasks["research"].output = raw
        self.tasks["budget"].output = self.output("budget", BudgetResult, budget_data())
        route = itinerary_data()
        preserved = self.output("itinerary", ItineraryResult, route)
        self.assertTrue(self.tasks["itinerary"].guardrail(preserved)[0])
        self.assertIn("https://example.com/", set(map(str, preserved.pydantic.sources)))
        route["sources"] = ["https://example.com/"]
        self.assertTrue(self.tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, route))[0])

    def test_empty_research_and_all_unknown_prices(self):
        self.tasks["research"].output = self.output("research", ResearchResult,
            dict(places=[], uncertainties=["Источники недоступны"]))
        data = budget_data()
        for item in data["expenses"]:
            item.update(amount=None, kind="unknown", place_ids=[])
        data.update(known_total="0", complete=False)
        budget = self.output("budget", BudgetResult, data)
        self.assertTrue(self.tasks["budget"].guardrail(budget)[0])
        self.tasks["budget"].output = budget
        route = itinerary_data()
        route.update(known_total="0", complete=False, budget_status="undetermined")
        for day in route["days"]: day["place_ids"] = []
        self.assertTrue(self.tasks["itinerary"].guardrail(self.output("itinerary", ItineraryResult, route))[0])
