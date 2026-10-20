export type RiskLevel = 'low' | 'medium' | 'high' | 'unknown';
export type RiskCategory = 'weather' | 'budget' | 'transport' | 'fatigue';

export interface RiskWeather {
  data_kind: 'forecast' | 'seasonal_baseline' | 'unavailable';
  observed_at: string | null;
  forecast_end_date?: string | null;
  precipitation_mm?: number | null;
  precipitation_probability_pct?: number | null;
  high_c?: number | null;
  low_c?: number | null;
  wind_speed_kph?: number | null;
  condition_code?: number | null;
  source_label?: string;
  source_ids?: string[];
}
export interface RiskCost {
  item_id: string;
  name: string;
  amount_cny: number | null;
  upper_cny?: number | null;
  basis: 'estimate' | 'quote' | 'paid' | 'unknown';
  source_ids?: string[];
}
export interface RiskTransport {
  item_id: string;
  name: string;
  route_status: 'ready' | 'estimated' | 'missing';
  duration_minutes: number | null;
  available_minutes: number | null;
  source_ids?: string[];
}
export interface RiskConnection {
  name: string;
  available_minutes: number;
  required_minutes: number;
  entity_ids?: string[];
}
export interface RiskDay {
  day_id: string;
  date: string;
  destination: string;
  outdoor_minutes: number | null;
  active_minutes: number | null;
  walking_km: number | null;
  rest_minutes: number | null;
  transport_coverage?: 'verified' | 'estimated' | 'missing' | 'none_required' | 'unknown' | null;
  walking_km_estimated?: boolean;
  active_minutes_estimated?: boolean;
  rest_minutes_estimated?: boolean;
  outdoor_minutes_estimated?: boolean;
  weather: RiskWeather;
  transport_complete: boolean;
  transports: RiskTransport[];
  connections: RiskConnection[];
  entity_ids?: string[];
}
export interface RiskInput {
  title: string;
  is_example: boolean;
  budget_cap_cny: number | null;
  costs_complete: boolean;
  costs: RiskCost[];
  days: RiskDay[];
  limits: {
    max_daily_walking_km: number;
    max_daily_active_hours: number;
    min_daily_rest_minutes: number;
  };
}
export interface RiskEvidence {
  field: string;
  label: string;
  value: number | string | boolean | null;
  unit: string;
  source_label: string;
  source_ids: string[];
  observed_at: string | null;
}
export interface RiskExplanation {
  data: RiskEvidence[];
  calculation: { expression: string; result: number | string | null; unit: string }[];
  rule: string;
  risk_level: RiskLevel;
  explanation: string;
}
export interface RiskFinding {
  rule_id: string;
  level: RiskLevel;
  title: string;
  reason: string;
  suggestion: string;
  explanation: RiskExplanation;
  day_id: string | null;
  entity_ids: string[];
  source_ids: string[];
}
export interface RiskDimension {
  category: RiskCategory;
  label: string;
  level: RiskLevel;
  coverage: 'complete' | 'partial' | 'missing';
  summary: string;
  explanation: RiskExplanation;
  metrics: Record<string, number | string | null>;
  findings: RiskFinding[];
  missing_data: string[];
  estimated_data: string[];
}
export interface RiskReport {
  engine_version: string;
  assessed_at: string;
  title: string;
  is_example: boolean;
  input_origin: 'manual' | 'journeypilot';
  bundle_id: string | null;
  overall_level: RiskLevel;
  data_complete: boolean;
  summary: string;
  dimensions: RiskDimension[];
  assumptions: string[];
}
export type RiskOptimizationStatus = 'applied' | 'needs_confirmation';
export interface RiskOptimizationProposal {
  proposal_id: string;
  category: RiskCategory;
  rule_id: string | null;
  day_id: string | null;
  field: string;
  title: string;
  reason: string;
  before: number | string | null;
  after: number | string | null;
  unit: string;
  status: RiskOptimizationStatus;
  requires_confirmation: boolean;
}
export interface RiskOptimizationResult {
  engine_version: string;
  original_input: RiskInput;
  optimized_input: RiskInput;
  before: RiskReport;
  after: RiskReport;
  proposals: RiskOptimizationProposal[];
  applied_count: number;
  pending_count: number;
  summary: string;
}
export interface TripRiskReview {
  input: RiskInput;
  assessment: RiskReport;
}

export interface DatasetEndpoint {
  name: string;
  place_id: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface DatasetSource {
  citation_id: string;
  source_type: 'official_api' | 'third_party_api' | 'public_web' | 'program_estimate' | 'unknown';
  provider: string;
  title: string;
  url: string | null;
  retrieved_at: string | null;
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
  fact_assertion_ids: string[];
}

export interface DatasetAssumption {
  code: string;
  text: string;
}

export interface DatasetWeather {
  data_kind: 'forecast' | 'seasonal_baseline' | 'observation' | 'unavailable';
  forecast_end_date: string | null;
  condition_label: string | null;
  high_c: number | null;
  low_c: number | null;
  precipitation_mm: number | null;
  precipitation_probability_pct: number | null;
  wind_speed_kph: number | null;
  condition_code: number | null;
  retrieved_at: string | null;
  source_ids: string[];
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
}

export interface DatasetActivity {
  activity_id: string;
  entity_type: 'visit_stop' | 'custom_block';
  name: string;
  place_id: string | null;
  address: string | null;
  visit_type: string | null;
  start_at: string | null;
  end_at: string | null;
  duration_minutes: number | null;
  ticket_cny: number | null;
  price_type: 'actual_quote' | 'estimated' | 'unknown';
  outdoor: boolean | null;
  source_ids: string[];
  retrieved_at: string | null;
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
  assumptions: DatasetAssumption[];
}

export interface DatasetMeal {
  meal_id: string;
  meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'other';
  status: 'planned' | 'not_planned' | 'unknown';
  restaurant_name: string | null;
  place_id: string | null;
  address: string | null;
  start_at: string | null;
  end_at: string | null;
  duration_minutes: number | null;
  party_size: number | null;
  per_person_cny: number | null;
  total_cny: number | null;
  price_type: 'actual_quote' | 'estimated' | 'unknown';
  price_basis: string | null;
  source_ids: string[];
  retrieved_at: string | null;
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
  assumptions: DatasetAssumption[];
}

export interface DatasetLodging {
  stay_id: string;
  name: string;
  address: string | null;
  check_in_date: string;
  check_out_date: string;
  nights: number;
  room_count: number | null;
  guest_count: number | null;
  nightly_cny: number | null;
  total_cny: number | null;
  price_type: 'actual_quote' | 'estimated' | 'unknown';
  price_basis: string | null;
  availability_status: 'confirmed' | 'needs_confirmation' | 'unavailable' | 'unknown';
  includes: string[];
  source_ids: string[];
  retrieved_at: string | null;
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
  assumptions: DatasetAssumption[];
}

export interface DatasetRouteStep {
  mode: string;
  from_name: string;
  to_name: string;
  line_name: string | null;
  service_number: string | null;
  departure_at: string | null;
  arrival_at: string | null;
  duration_minutes: number | null;
  distance_m: number | null;
  fare_cny: number | null;
}

export interface DatasetRoute {
  route_id: string;
  transport_leg_id: string | null;
  from_endpoint: DatasetEndpoint;
  to_endpoint: DatasetEndpoint;
  mode: string;
  route_status: 'ready' | 'estimated' | 'missing';
  departure_at: string | null;
  arrival_at: string | null;
  duration_minutes: number | null;
  distance_m: number | null;
  distance_source: string;
  distance_method: string | null;
  fare_cny: number | null;
  price_type: 'actual_quote' | 'estimated' | 'unknown';
  transfer_count: number;
  steps: DatasetRouteStep[];
  source_ids: string[];
  retrieved_at: string | null;
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
  assumptions: DatasetAssumption[];
}

export interface DatasetMetrics {
  activity_minutes: number | null;
  transport_minutes: number | null;
  walking_m: number | null;
  walking_km: number | null;
  outdoor_minutes: number | null;
  rest_minutes: number | null;
  transfers: number;
  estimated_fields: string[];
}

export interface DatasetTimelineItem {
  order: number;
  kind: 'activity' | 'meal' | 'route' | 'lodging';
  id: string;
}

export interface DatasetDay {
  day_id: string;
  day_index: number;
  date: string;
  timezone: string | null;
  destination_id: string;
  destination_name: string;
  start_place: DatasetEndpoint | null;
  end_place: DatasetEndpoint | null;
  timeline: DatasetTimelineItem[];
  activities: DatasetActivity[];
  meals: DatasetMeal[];
  routes: DatasetRoute[];
  lodging_stay_id: string | null;
  weather: DatasetWeather | null;
  metrics: DatasetMetrics;
  warnings: string[];
  assumptions: DatasetAssumption[];
}

export interface DatasetCostItem {
  cost_id: string;
  category: 'transport' | 'dining' | 'lodging' | 'ticket' | 'other';
  label: string;
  amount_cny: number | null;
  low_cny: number | null;
  high_cny: number | null;
  currency: 'CNY';
  unit_scope: 'per_person' | 'per_room_night' | 'per_group' | 'per_item' | 'unknown';
  quantity: number | null;
  unit_label: string | null;
  price_type: 'actual_quote' | 'estimated' | 'unknown';
  price_basis: string | null;
  source_ids: string[];
  confidence: 'verified' | 'estimated' | 'unverified' | 'unknown';
}

export interface AmountRange {
  currency: 'CNY';
  low_cny: number | null;
  high_cny: number | null;
  point_cny: number | null;
}

export interface DatasetCosts {
  items: DatasetCostItem[];
  transport: AmountRange;
  dining: AmountRange;
  lodging: AmountRange;
  ticket: AmountRange;
  other: AmountRange;
  total: AmountRange;
  priced_item_count: number;
  unknown_item_count: number;
  complete: boolean;
  computed_by: 'backend';
}

export interface DatasetDataSource {
  source_id: string;
  name: string;
  kind: 'weather' | 'search' | 'route' | 'place' | 'flight' | 'hotel';
  configured: boolean;
  capabilities: string[];
  required_env: string[];
  note: string;
}

export interface TripDataset {
  schema_version: 'trip-dataset.v1';
  dataset_id: string;
  generated_at: string;
  trip: {
    run_id: string;
    bundle_id: string;
    itinerary_id: string;
    title: string;
    destination_ids: string[];
    destination_names: string[];
    start_date: string;
    end_date: string;
    timezone: string | null;
    party: {
      adults: number;
      children: number;
      elderly_companions: boolean;
      accessibility_required: boolean;
    };
    preferences: { style: string | null; interests: string[]; requirements: string[] };
  };
  days: DatasetDay[];
  lodgings: DatasetLodging[];
  costs: DatasetCosts;
  sources: DatasetSource[];
  data_sources: DatasetDataSource[];
  coverage: { warnings: string[]; missing_fields: string[]; estimated_fields: string[] };
}

export interface DatasetImportSummary {
  dataset_id: string;
  schema_version: string;
  bundle_id: string;
  title: string;
  destinations: string[];
  start_date: string;
  end_date: string;
  day_count: number;
  budget_cap_cny: number | null;
  estimated_total: AmountRange;
  cost_coverage: 'complete' | 'partial' | 'missing' | string;
  priced_cost_count: number;
  unknown_cost_count: number;
  estimated_fields: string[];
  missing_fields: string[];
  warnings: string[];
  source_count: number;
  data_sources: DatasetDataSource[];
}

export interface DatasetImportResponse {
  dataset: TripDataset;
  input: RiskInput;
  import_summary: DatasetImportSummary;
}

export interface DatasetRiskReview {
  input: RiskInput;
  assessment: RiskReport;
  import_summary: DatasetImportSummary;
}
