"""One real run of the saved user case against the desktop API; no automatic retries."""
import json
from datetime import timedelta
from pathlib import Path
import time
import httpx
from travel_planner.api import TripResultResponse
from travel_planner.models import TripInput
from travel_planner.planning import research_quality, budget_quality, itinerary_quality, itinerary_feedback
from travel_planner.settings import PROJECT_ROOT


def main():
    trip = TripInput.model_validate_json((PROJECT_ROOT/'examples/minsk-case.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=15, trust_env=False) as client:
        response = client.post('/trips', json=trip.model_dump(mode='json'))
        response.raise_for_status()
        trip_id = response.json()['trip_id']
        print(json.dumps(dict(trip_id=trip_id, accepted=response.status_code)), flush=True)
        begin = time.monotonic()
        previous = None
        while time.monotonic()-begin < 450:
            state = client.get('/trips/'+trip_id).json()
            current = (state['status'], state['current_task'])
            if current != previous:
                print(json.dumps(dict(status=current[0], task=current[1])), flush=True)
                previous = current
            if state['status'] in ('completed','failed'): break
            time.sleep(2)
        response = client.get('/trips/'+trip_id+'/result')
        if state['status'] != 'completed' or response.status_code != 200:
            print(json.dumps(dict(trip_id=trip_id, status=state['status'], result_http=response.status_code)), flush=True)
            return 1
        model = TripResultResponse.model_validate(response.json())
        saved = json.loads((PROJECT_ROOT/'results/api'/(trip_id+'.json')).read_text(encoding='utf-8'))
        assert saved['status']=='success' and saved['worker_stopped'] and all(saved['checks'].values())
        assert saved['trip']==trip.model_dump(mode='json')
        assert saved['final']==response.json()['final']
        assert [d.date for d in model.final.days]==[trip.start_date+timedelta(days=i) for i in range(trip.days)]
        assert model.final.known_total==model.tasks.budget.known_total
        assert research_quality(model.tasks.research,trip) is None
        assert budget_quality(model.tasks.budget,model.tasks.research,trip) is None
        assert itinerary_quality(model.final,model.tasks.research,trip) is None
        assert itinerary_feedback(model.final,model.tasks.budget,model.tasks.research,trip) is None
        coverage={p.category for p in model.tasks.research.places}
        density=[len(day.place_ids) for day in model.final.days]
        evidence=dict(place_count=len(model.tasks.research.places),categories=sorted(coverage),places_per_day=density,trip_id=trip_id,success=True,result_http=200,checks=saved['checks'],duration_seconds=round(time.monotonic()-begin,2))
        (PROJECT_ROOT/'results'/('minsk-check-'+trip_id+'.json')).write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(json.dumps(evidence),flush=True)
        return 0

if __name__=='__main__':
    raise SystemExit(main())
