"""Суммы всей поездки и группы; без конвертации и умножения."""

from decimal import Decimal, localcontext
from typing import Annotated

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=100, decimal_places=30)]


def reject_boolean(value):
    if isinstance(value, bool):
        raise ValueError("Сумма должна быть числом, не логическим значением")
    return value


class Expense(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, description="Название статьи расходов")
    amount: Money = Field(description="Полная сумма статьи для всей поездки и группы; строка предпочтительна")

    _amount_check = field_validator("amount", mode="before")(reject_boolean)


class TripCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expenses: list[Expense] = Field(min_length=1, max_length=1000, description="Полные суммы статей, без повторного умножения")
    currency: str = Field(min_length=1, max_length=12, description="Единая валюта всех сумм, например RUB")
    budget: Money | None = Field(default=None, description="Необязательный общий бюджет всей поездки и группы")

    _budget_check = field_validator("budget", mode="before")(reject_boolean)


class TripCostCalculatorTool(BaseTool):
    name: str = "trip_cost_calculator"
    description: str = (
        "Складывает полные расходы всей поездки и группы в единой валюте. "
        "Не умножает на людей или дни и не конвертирует валюту. "
        "При наличии общего бюджета возвращает остаток или превышение."
    )
    args_schema: type[BaseModel] = TripCostInput

    def _run(self, expenses: list, currency: str, budget=None) -> dict:
        data = TripCostInput.model_validate({"expenses": expenses, "currency": currency, "budget": budget})
        # 100 значащих цифр + 30 дробных + запас для суммы 1000 статей.
        with localcontext() as context:
            context.prec = 140
            total = sum((item.amount for item in data.expenses), Decimal(0))
            remaining = over_budget = None
            status = None
            if data.budget is not None:
                difference = data.budget - total
                remaining = format(max(difference, Decimal(0)), "f")
                over_budget = format(max(-difference, Decimal(0)), "f")
                status = "remaining" if difference > 0 else "exceeded" if difference < 0 else "equal"
            return {"status": "ok", "total": format(total, "f"), "currency": data.currency,
                    "budget": format(data.budget, "f") if data.budget is not None else None,
                    "budget_status": status, "remaining": remaining, "over_budget": over_budget}
