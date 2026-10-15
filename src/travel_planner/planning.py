"""Program density and interest coverage; no model or network dependencies."""
import re
import json
from collections import Counter
from datetime import timedelta


def requested_categories(trip):
    text=' '.join(trip.interests).casefold()
    patterns={'museum':r'музе|museum', 'architecture':r'архитект|architecture',
              'food':r'покуш|кухн|ресторан|кафе|поесть|вкусн|food|cuisine',
              'shopping':r'\bтц\b|торгов|шоп|shopping|mall', 'nature':r'природ|парк|nature'}
    return {key for key, pattern in patterns.items() if re.search(pattern,text)}


def place_target(trip):
    return min(24,max(4,3*(trip.days-2))) if trip.days>=3 else min(6,trip.days*3)


def research_quality(research,trip):
    # Preserve old short-trip contracts. Long programs must have sufficient material.
    if trip.days<3: return None
    target=place_target(trip)
    if len(research.places)<target:
        return f'Недостаточно мест: {len(research.places)}; для {trip.days} дней подбери минимум {target} разных мест. Расширь поиск по интересам, включая еду и бесплатную архитектуру; не выдумывай сведения.'
    missing=requested_categories(trip)-{p.category for p in research.places}
    if missing: return 'Не покрыты интересы: '+', '.join(sorted(missing))+'. Выполни отдельные поиски и добавь конкретные места этих категорий.'
    if any(not any((p.description.sources,p.conditions.sources,p.hours.sources,p.price.sources)) for p in research.places):
        return 'Каждое место должно иметь хотя бы один веб-источник, подтверждающий его существование.'
    if 'food' in requested_categories(trip) and sum(p.category=='food' for p in research.places)<min(8,trip.days-2):
        return 'Нужны разные конкретные кафе/рестораны на полные дни, а не общая рекомендация поесть.'
    return None


def budget_quality(budget,research,trip):
    if trip.days<3: return None
    selected={p for item in budget.expenses for p in item.place_ids}
    if len(selected)<place_target(trip):
        return 'В смете выбрано слишком мало мест. Сохрани минимум '+str(place_target(trip))+' мест из исследования, включая бесплатные и еду. Группируй статьи, неизвестные цены оставляй null.'
    missing=requested_categories(trip)-{p.category for p in research.places if p.id in selected}
    if missing: return 'Смета потеряла интересы: '+', '.join(sorted(missing))+'. Включи соответствующие place_ids.'
    if 'food' in requested_categories(trip):
        food_ids = [p.id for p in research.places if p.category == 'food']
        needed = min(8, trip.days - 2)
        if len(selected.intersection(food_ids)) < needed:
            return (f'На {trip.days - 2} полных дней выбрано недостаточно заведений. '
                    f'Включи в food.place_ids минимум {needed} разных id из '
                    + json.dumps(food_ids, ensure_ascii=False)
                    + '. Сохрани общий бюджет питания, не начисляй его повторно в activities; затем проверь калькулятором окончательную смету.')
    return None


def itinerary_quality(route,research,trip):
    if trip.days<3: return None
    categories={p.id:p.category for p in research.places}
    full_days = trip.days - 2
    wants_food = 'food' in requested_categories(trip)
    minimum = min(3 if wants_food else 2, len(research.places) // full_days)
    daily_food = wants_food and full_days <= sum(p.category == 'food' for p in research.places)
    for day in route.days[1:-1]:
        if len(day.place_ids) < minimum:
            return f'День {day.date} недостаточно наполнен. Распредели выбранные места: минимум {minimum} места в полный день, включая еду, утром/днём/вечером, с дорогой и отдыхом.'
        if daily_food and not any(categories.get(p)=='food' for p in day.place_ids):
            return f'В день {day.date} не выбран ресторан/кафе. Включи конкретное место еды из исследования и сметы, не добавляя новых расходов.'
    return None


def allocation_seed(budget, research, trip):
    """A feasible ID-only draft, not invented schedules, prices or verified opening hours."""
    days = [dict(date=(trip.start_date + timedelta(days=i)).isoformat(), place_ids=[])
            for i in range(trip.days)]
    slots = days[1:-1] or days[:1]
    selected = {p for item in budget.expenses for p in item.place_ids}
    places = [p for p in research.places if p.id in selected]
    food = [p for p in places if p.category == 'food']
    assigned = set()
    for day, place in zip(slots, food):
        day['place_ids'].append(place.id)
        assigned.add(place.id)
    for place in places:
        if place.id not in assigned:
            min(slots, key=lambda d: len(d['place_ids']))['place_ids'].append(place.id)
    return days


def itinerary_feedback(route, budget, research, trip):
    """Report coverage and daily constraints together so one repair can fix all of them."""
    selected = {p for item in budget.expenses for p in item.place_ids}
    visits = [p for day in route.days for p in day.place_ids]
    counts = Counter(visits)
    issues = {}
    duplicates = {p: [str(d.date) for d in route.days if p in d.place_ids]
                  for p, n in counts.items() if n > 1}
    if duplicates: issues['duplicate'] = duplicates
    if selected - set(visits): issues['missing'] = sorted(selected - set(visits))
    if set(visits) - selected: issues['unexpected'] = sorted(set(visits) - selected)
    if trip.days >= 3:
        by_id = {p.id: p for p in research.places}
        wants_food = 'food' in requested_categories(trip)
        minimum = min(3 if wants_food else 2, len(selected) // (trip.days - 2))
        underfilled = [str(d.date) for d in route.days[1:-1] if len(d.place_ids) < minimum]
        if underfilled: issues['underfilled'] = dict(dates=underfilled, minimum=minimum)
        if wants_food and trip.days - 2 <= sum(p.category == 'food' for p in research.places):
            missing_food = [str(d.date) for d in route.days[1:-1]
                            if not any(by_id.get(p) and by_id[p].category == 'food' for p in d.place_ids)]
            if missing_food: issues['missing_food'] = missing_food
    if not issues: return None
    return ('Исправь ВСЕ нарушения распределения за один ответ: '
            + json.dumps(issues, ensure_ascii=False)
            + '. Не добавляй повтор ради наполнения дня: перенеси уникальные места с перегруженного дня. '
            'Сохрани все выбранные id и смету. Рабочий черновик распределения: '
            + json.dumps(allocation_seed(budget, research, trip), ensure_ascii=False)
            + '. Можно менять дни/порядок ради часов работы и районов, но без повторов, пропусков и пустых полных дней. '
            'Верни полный JSON маршрута, без служебных полей черновика.')
