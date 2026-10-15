"""Компактные контракты этапа 4. Импорт не требует CrewAI и сети."""
from datetime import date
from decimal import Decimal, localcontext
from typing import Annotated, Literal

from pydantic import (BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl,
                      PlainSerializer, model_validator)


def exact_money(value):
    if isinstance(value, (bool, float)):
        raise ValueError("Деньги передавайте десятичной строкой, Decimal или int")
    return value


Money = Annotated[Decimal, BeforeValidator(exact_money),
                  Field(ge=0, allow_inf_nan=False, max_digits=100, decimal_places=30),
                  PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json")]
Text = Annotated[str, Field(min_length=1)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Kind = Literal["fact", "estimate", "unknown"]
# CrewAI 1.15.28's execution-storage encoder calls model_dump() in Python mode.
# Keep URL validation while making that representation JSON-compatible too.
SourceURL = Annotated[HttpUrl, PlainSerializer(str, return_type=str)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TripInput(Contract):
    departure_city: Text
    destination: Text
    start_date: date
    end_date: date
    budget: Money
    currency: Currency
    travelers: int = Field(gt=0, strict=True)
    interests: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("Окончание поездки раньше начала")
        return self

    @property
    def days(self) -> int:
        """Обе даты включены; одинаковые даты означают один день."""
        return (self.end_date - self.start_date).days + 1


class Evidence(Contract):
    kind: Kind
    sources: list[SourceURL] = Field(default_factory=list, max_length=3)
    note: Text

    @model_validator(mode="after")
    def fact_needs_source(self):
        if self.kind == "fact" and not self.sources:
            raise ValueError("Факт требует источник")
        return self


class Finding(Evidence):
    text: Text | None

    @model_validator(mode="after")
    def known_text(self):
        if (self.kind == "unknown") != (self.text is None):
            raise ValueError("unknown требует null; факт/оценка требуют текст")
        return self


class Price(Evidence):
    amount: Money | None
    currency: Currency | None

    @model_validator(mode="after")
    def known_price(self):
        if self.kind == "unknown":
            if self.amount is not None:
                raise ValueError("Неизвестная цена должна быть null")
        elif self.amount is None or self.currency is None:
            raise ValueError("Известная цена требует сумму и валюту")
        return self


class Place(Contract):
    id: Text
    name: Text
    description: Finding
    conditions: Finding
    hours: Finding
    price: Price


def unique(values):
    if len(values) != len(set(values)):
        raise ValueError("Повторяющиеся идентификаторы")


class ResearchResult(Contract):
    places: list[Place] = Field(max_length=4)
    uncertainties: list[Text]

    @model_validator(mode="after")
    def place_ids(self):
        unique([place.id for place in self.places])
        if not self.places and not self.uncertainties:
            raise ValueError("Пустое исследование требует объяснения")
        return self


class CostItem(Evidence):
    id: Text
    category: Literal["transport", "lodging", "food", "activities", "other"]
    name: Text
    amount: Money | None
    place_ids: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def cost_contract(self):
        if (self.kind == "unknown") != (self.amount is None):
            raise ValueError("Неизвестная сумма — null, известная — число")
        unique(self.place_ids)
        if self.category != "activities" and self.place_ids:
            raise ValueError("Только статья activities может ссылаться на места")
        return self


class BudgetResult(Contract):
    currency: Currency
    expenses: list[CostItem] = Field(min_length=4, max_length=12)
    known_total: Money
    complete: bool = Field(strict=True)
    logistics: list[Finding] = Field(min_length=1, max_length=4)
    assumptions: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def totals(self):
        unique([item.id for item in self.expenses])
        categories = {item.category for item in self.expenses}
        if not {"transport", "lodging", "food", "activities"} <= categories:
            raise ValueError("Нужны основные категории расходов")
        unique([p for item in self.expenses for p in item.place_ids])
        with localcontext() as context:
            context.prec = 140
            total = sum((item.amount for item in self.expenses if item.amount is not None), Decimal(0))
        if self.known_total != total:
            raise ValueError("known_total не равен сумме известных полных статей")
        if self.complete and any(item.amount is None for item in self.expenses):
            raise ValueError("Смета с неизвестными расходами неполная")
        return self


class RouteDay(Contract):
    date: date
    place_ids: list[Text]
    schedule: Finding
    movements: Finding

    @model_validator(mode="after")
    def ids(self):
        unique(self.place_ids)
        return self


class ItineraryResult(Contract):
    days: list[RouteDay] = Field(min_length=1)
    currency: Currency
    known_total: Money
    complete: bool = Field(strict=True)
    budget_status: Literal["remaining", "equal", "exceeded", "undetermined"]
    over_budget: Money
    sources: list[SourceURL]
    caveats: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def dates(self):
        for previous, current in zip(self.days, self.days[1:]):
            if (current.date - previous.date).days != 1:
                raise ValueError("Дни должны следовать подряд без повторов")
        return self
