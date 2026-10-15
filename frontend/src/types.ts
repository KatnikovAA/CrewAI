export type TaskName = 'research' | 'budget' | 'itinerary';
export type Kind = 'fact' | 'estimate' | 'unknown';
export interface Evidence {kind:Kind; sources:string[]; note:string}
export interface Finding extends Evidence {text:string|null}
export interface Price extends Evidence {amount:string|null;currency:string|null}
export interface Place {category?:'museum'|'architecture'|'food'|'shopping'|'nature'|'other';id:string;name:string;description:Finding;conditions:Finding;hours:Finding;price:Price}
export interface Cost extends Evidence {id:string;category:string;name:string;amount:string|null;place_ids:string[]}
export interface TripInput {departure_city:string;destination:string;start_date:string;end_date:string;budget:string;currency:string;travelers:number;interests:string[]}
export interface Draft extends Omit<TripInput,'travelers'|'interests'> {travelers:string;interests:string}
export type FieldErrors=Partial<Record<keyof Draft,string>>;
export interface ProgressEvent {seq:number;timestamp:string;type:string;task:TaskName|null;tool?:string|null;status?:string|null;from_cache?:boolean|null}
export interface TripState {trip_id:string;status:'queued'|'running'|'completed'|'failed';current_task:TaskName|null;created_at:string;started_at:string|null;finished_at:string|null;events:ProgressEvent[];events_total:number;error:{code:string;message:string}|null}
export interface RouteDay {date:string;place_ids:string[];schedule:Finding;movements:Finding}
export interface TripResult {trip_id:string;final:{days:RouteDay[];currency:string;known_total:string;complete:boolean;budget_status:'remaining'|'equal'|'exceeded'|'undetermined';over_budget:string;sources:string[];caveats:string[]};tasks:{research:{places:Place[];uncertainties:string[]};budget:{currency:string;expenses:Cost[];known_total:string;complete:boolean;logistics:Finding[];assumptions:string[]};itinerary:TripResult['final']}}
export interface Accepted {trip_id:string;status_url:string;result_url:string}
