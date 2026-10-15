"""Одна последовательная Crew из фабрик этапов 1–4; без запуска."""
from travel_planner.runtime import configure_runtime
from travel_planner.agents import create_agents
from travel_planner.tasks import create_tasks
from travel_planner.models import TripInput
from travel_planner.llm import create_llm
import json
from decimal import Decimal


def create_crew(trip: TripInput, *, llm=None, tools=None, task_callback=None):
    configure_runtime()
    from crewai import Crew, Process
    trip = TripInput.model_validate(trip.model_dump())
    agents = create_agents(llm=create_llm(max_tokens=6000, timeout=60) if llm is None else llm, tools=tools)
    tasks = create_tasks(trip, agents)
    for name, task in tasks.items():
        task.name = name

    def completed(output):
        if output is tasks["budget"].output:
            # Explicit projection of validated context; no facts/prices are invented.
            # The planner must still execute its own calculator call and pass guardrail.
            from travel_planner.tasks import _sources
            from travel_planner.tools.calculator import TripCostCalculatorTool
            costs = output.pydantic
            known = [dict(name=item.id, amount=format(item.amount, "f"))
                     for item in costs.expenses if item.amount is not None]
            checked = TripCostCalculatorTool()._run(
                expenses=known or [dict(name="Нет известных расходов", amount="0")],
                currency=costs.currency, budget=format(trip.budget, "f"))
            status = checked["budget_status"]
            if not costs.complete and Decimal(checked["over_budget"]) == 0:
                status = "undetermined"
            values = dict(currency=costs.currency, known_total=checked["total"],
                          complete=costs.complete, budget_status=status, over_budget=checked["over_budget"],
                          sources=sorted(_sources(tasks["research"].output.pydantic) | _sources(costs)),
                          selected_place_ids=[p for item in costs.expenses for p in item.place_ids])
            tasks["itinerary"].expected_output += (
                "\nОбязательные значения из валидированного контекста; сохрани ВСЕ sources "
                "и распредели selected_place_ids по дням ровно по одному разу: "
                + json.dumps(values, ensure_ascii=False))
        if task_callback:
            return task_callback(output)

    return Crew(agents=list(agents.values()), tasks=list(tasks.values()),
                process=Process.sequential, memory=False, planning=False,
                cache=False, verbose=False, tracing=False,
                task_callback=completed)
