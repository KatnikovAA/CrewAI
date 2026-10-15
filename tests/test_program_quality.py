"""Behavioral regressions for populated, diverse multi-day travel plans."""
from copy import deepcopy
from datetime import timedelta
import unittest
from pydantic import ValidationError
from test_tasks import trip_data, research_data, budget_data, itinerary_data
from travel_planner.models import TripInput, ResearchResult, BudgetResult, ItineraryResult

class ProgramQualityTests(unittest.TestCase):
    def trip(self):
        data=trip_data(); data['end_date']='2026-11-07'; data['interests']=['Музеи', 'вкусно покушать и архитектура и ТЦ']
        return TripInput(**data)

    def research(self):
        place=research_data()['places'][0]
        places=[]
        for i in range(15):
            p=deepcopy(place); p.update(id=f'p{i}',category=['museum','architecture','food','shopping','food'][i%5])
            p['description'].update(text=f'Объект {i}',kind='fact',sources=['https://example.com/'])
            places.append(p)
        return ResearchResult(places=places,uncertainties=['Часы требуют проверки'])

    def test_expanded_research_and_all_interest_categories(self):
        from travel_planner.planning import research_quality
        self.assertIsNone(research_quality(self.research(),self.trip()))
        sparse=ResearchResult(**research_data())
        self.assertIsNotNone(research_quality(sparse,self.trip()))
        data=self.research().model_dump();
        for p in data['places']: p['category']='museum'
        self.assertIsNotNone(research_quality(ResearchResult(**data),self.trip()))

    def test_food_places_linked_once_without_extra_activity_charge(self):
        data=budget_data(); data['expenses'][2]['place_ids']=['restaurant']
        budget=BudgetResult(**data)
        self.assertEqual(budget.known_total, __import__('decimal').Decimal('0.40'))
        data['expenses'][3]['place_ids'].append('restaurant')
        with self.assertRaises(ValidationError): BudgetResult(**data)

    def test_no_empty_full_days_when_places_available(self):
        from travel_planner.planning import itinerary_quality
        trip=self.trip(); data=itinerary_data(); days=[]
        for i in range(7):
            day=deepcopy(data['days'][0]); day['date']=trip.start_date+timedelta(days=i)
            day['place_ids']=[f'p{(i-1)*3+j}' for j in range(3)] if 0<i<6 else []
            days.append(day)
        data['days']=days
        route=ItineraryResult(**data)
        self.assertIsNone(itinerary_quality(route,self.research(),trip))
        route.days[3].place_ids=[]
        self.assertIsNotNone(itinerary_quality(route,self.research(),trip))

    def test_budget_cannot_drop_categories_or_most_places(self):
        from travel_planner.planning import budget_quality
        data=budget_data()
        data['expenses'][3]['place_ids']=[p.id for p in self.research().places]
        budget=BudgetResult(**data)
        self.assertIsNone(budget_quality(budget,self.research(),self.trip()))
        budget.expenses[3].place_ids=['p0']
        self.assertIsNotNone(budget_quality(budget,self.research(),self.trip()))

    def test_places_require_sources_and_keep_bounded_size(self):
        from travel_planner.planning import research_quality
        data=self.research().model_dump()
        data['places'][0]['description'].update(kind='estimate',sources=[])
        self.assertIsNotNone(research_quality(ResearchResult(**data),self.trip()))
        data=self.research().model_dump()
        for i in range(10):
            p=deepcopy(data['places'][0]); p['id']=f'extra{i}'; data['places'].append(p)
        with self.assertRaises(ValidationError): ResearchResult(**data)

    def test_two_places_including_lunch_are_not_two_visits_plus_food(self):
        from travel_planner.planning import itinerary_quality
        trip=self.trip(); data=itinerary_data(); data['days']=[]
        for i in range(7):
            day=deepcopy(itinerary_data()['days'][0]); day['date']=trip.start_date+timedelta(days=i)
            day['place_ids']=['p0','p2'] if 0<i<6 else []
            data['days'].append(day)
        self.assertIsNotNone(itinerary_quality(ItineraryResult(**data),self.research(),trip))

    def test_budget_keeps_enough_food_for_each_full_day(self):
        from travel_planner.planning import budget_quality
        data=self.research().model_dump()
        for i in range(6):
            p=deepcopy(data['places'][0]); p.update(id=f'extra{i}',category='architecture'); data['places'].append(p)
        research=ResearchResult(**data)
        food=[p.id for p in research.places if p.category=='food']
        chosen=[p.id for p in research.places if p.id not in food[-2:]]
        data=budget_data(); data['expenses'][3]['place_ids']=chosen
        self.assertGreaterEqual(len(chosen),15)
        self.assertIsNotNone(budget_quality(BudgetResult(**data),research,self.trip()))

    def test_route_feedback_lists_repeats_and_missing_meal_together(self):
        from travel_planner.planning import itinerary_feedback
        trip=self.trip(); research=self.research(); data=itinerary_data(); data['days']=[]
        for i in range(7):
            d=deepcopy(itinerary_data()['days'][0]);d['date']=trip.start_date+timedelta(days=i); d['place_ids']=['p0','p1'] if 0<i<6 else [];data['days'].append(d)
        budget=budget_data();budget['expenses'][3]['place_ids']=[p.id for p in research.places]
        feedback=itinerary_feedback(ItineraryResult(**data),BudgetResult(**budget),research,trip)
        self.assertIn('p0',feedback)
        self.assertIn('duplicate',feedback)
        self.assertIn('missing_food',feedback)
        self.assertIn('underfilled',feedback)

    def test_seed_plan_uses_all_places_once_and_meal_each_full_day(self):
        from travel_planner.planning import allocation_seed
        trip=self.trip();research=self.research(); budget=budget_data();budget['expenses'][3]['place_ids']=[p.id for p in research.places]
        seed=allocation_seed(BudgetResult(**budget),research,trip)
        ids=[p for day in seed for p in day['place_ids']]
        self.assertEqual(set(ids),{p.id for p in research.places})
        self.assertEqual(len(ids),len(set(ids)))
        categories={p.id:p.category for p in research.places}
        for day in seed[1:-1]:
            self.assertGreaterEqual(len(day['place_ids']),3)
            self.assertTrue(any(categories[p]=='food' for p in day['place_ids']))
