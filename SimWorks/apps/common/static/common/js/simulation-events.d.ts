/**
 * WebSocket Event Schema for MedSim simulations.
 *
 * This file documents the event types consumed by web and mobile clients
 * via the SimulationSocket WebSocket connection.
 *
 * WebSocket Endpoint: ws://{host}/ws/simulation/{simulation_id}/
 *
 * Usage:
 *   - Web: Listen for `sim:{event_type}` CustomEvents on window
 *   - Mobile: Parse JSON messages from WebSocket directly
 */

// ============================================================================
// Shared Event Types
// ============================================================================

export type TransientSimulationEventType =
    // Connection events (dispatched by SimulationSocket, not durable outbox events)
    | 'connected'
    | 'disconnected'

    // Initialization
    | 'init_message'
    | 'error'

    | 'typing'
    | 'stopped_typing'

    // Compatibility / transient workflow events outside the canonical outbox contract
    | 'simulation.feedback.continue_conversation'
    | 'simulation.hotwash.continue_conversation';

export type CanonicalOutboxEventType =
    | 'message.item.created'
    | 'message.delivery.updated'
    | 'patient.metadata.created'
    | 'patient.results.updated'
    | 'feedback.item.created'
    | 'feedback.generation.failed'
    | 'feedback.generation.updated'
    | 'simulation.status.updated'
    | 'patient.injury.created'
    | 'patient.injury.updated'
    | 'patient.illness.created'
    | 'patient.illness.updated'
    | 'patient.problem.created'
    | 'patient.problem.updated'
    | 'patient.recommendedintervention.created'
    | 'patient.recommendedintervention.updated'
    | 'patient.recommendedintervention.removed'
    | 'patient.intervention.created'
    | 'patient.intervention.updated'
    | 'simulation.note.created'
    | 'patient.assessmentfinding.created'
    | 'patient.assessmentfinding.updated'
    | 'patient.assessmentfinding.removed'
    | 'patient.diagnosticresult.created'
    | 'patient.diagnosticresult.updated'
    | 'patient.resource.updated'
    | 'patient.disposition.updated'
    | 'patient.recommendationevaluation.created'
    | 'simulation.brief.created'
    | 'simulation.brief.updated'
    | 'patient.vital.created'
    | 'patient.vital.updated'
    | 'patient.pulse.created'
    | 'patient.pulse.updated'
    | 'simulation.annotation.created'
    | 'simulation.tick.triggered'
    | 'simulation.snapshot.updated'
    | 'simulation.plan.updated'
    | 'simulation.runtime.failed'
    | 'simulation.summary.updated'
    | 'simulation.adjustment.updated'
    | 'simulation.preset.updated'
    | 'simulation.command.updated'
    | 'simulation.patch.completed';

/**
 * Canonical outbox contract plus transient socket-only events.
 */
export type CanonicalSimulationEventType =
    | CanonicalOutboxEventType
    | TransientSimulationEventType;

/**
 * Deprecated aliases accepted during the migration window.
 */
export type DeprecatedSimulationEventType =
    | 'chat.message_created'
    | 'message_status_update'
    | 'simulation.feedback_created'
    | 'feedback.created'
    | 'simulation.hotwash.created'
    | 'metadata.created'
    | 'simulation.metadata.results_created'
    | 'simulation.state_changed'
    | 'feedback.failed'
    | 'feedback.retrying'
    | 'injury.created'
    | 'injury.updated'
    | 'illness.created'
    | 'illness.updated'
    | 'problem.created'
    | 'problem.updated'
    | 'problem.resolved'
    | 'recommended_intervention.created'
    | 'recommended_intervention.updated'
    | 'recommended_intervention.removed'
    | 'intervention.created'
    | 'intervention.updated'
    | 'note.created'
    | 'trainerlab.assessment_finding.created'
    | 'trainerlab.assessment_finding.updated'
    | 'trainerlab.assessment_finding.removed'
    | 'trainerlab.diagnostic_result.created'
    | 'trainerlab.diagnostic_result.updated'
    | 'trainerlab.resource.updated'
    | 'trainerlab.disposition.updated'
    | 'trainerlab.vital.created'
    | 'trainerlab.vital.updated'
    | 'trainerlab.pulse.created'
    | 'trainerlab.pulse.updated'
    | 'trainerlab.recommendation_evaluation.created'
    | 'trainerlab.scenario_brief.created'
    | 'trainerlab.scenario_brief.updated'
    | 'trainerlab.intervention.assessed'
    | 'trainerlab.annotation.created'
    | 'trainerlab.tick.triggered'
    | 'state.updated'
    | 'ai.intent.updated'
    | 'run.started'
    | 'run.paused'
    | 'run.resumed'
    | 'run.stopped'
    | 'runtime.failed'
    | 'summary.ready'
    | 'summary.updated'
    | 'session.seeding'
    | 'session.seeded'
    | 'session.failed'
    | 'adjustment.accepted'
    | 'adjustment.applied'
    | 'preset.applied'
    | 'command.accepted'
    | 'simulation.patch_evaluation.completed'
    | 'patient.assessment_finding.created'
    | 'patient.assessment_finding.updated'
    | 'patient.assessment_finding.removed'
    | 'patient.diagnostic_result.created'
    | 'patient.diagnostic_result.updated'
    | 'patient.recommendation_evaluation.created'
    | 'patient.recommended_intervention.created'
    | 'patient.recommended_intervention.updated'
    | 'patient.recommended_intervention.removed';

/**
 * All simulation event types accepted by clients.
 */
export type SimulationEventType = CanonicalSimulationEventType | DeprecatedSimulationEventType;

// ============================================================================
// Event Payloads
// ============================================================================

/**
 * Base event structure - all events have at minimum a type
 */
export interface BaseEvent {
    type: SimulationEventType;
}

/**
 * Connection established event (client-side only)
 */
export interface ConnectedEvent extends BaseEvent {
    type: 'connected';
    simulationId: string;
}

/**
 * Connection lost event (client-side only)
 */
export interface DisconnectedEvent extends BaseEvent {
    type: 'disconnected';
    code: number;
    reason: string;
}

/**
 * Initial message with patient display info
 * Sent by server on WebSocket connection
 */
export interface InitMessageEvent extends BaseEvent {
    type: 'init_message';
    sim_display_name: string;
    sim_display_initials: string;
}

/**
 * Error event
 */
export interface ErrorEvent extends BaseEvent {
    type: 'error';
    message: string;
    redirect?: string;
}

/**
 * Chat message created event
 */
export interface ChatMessageCreatedEvent extends BaseEvent {
    type: 'message.item.created' | 'chat.message_created';
    id: number;
    message_id?: number;
    content: string;
    role: 'user' | 'assistant';
    senderId: string;
    user: string;
    display_name?: string;
    displayName?: string;
    isFromLLM?: boolean;
    isFromAi?: boolean;
    status?: 'sent' | 'delivered' | 'read';
    conversation_id?: number;
    conversation_type?: string;
    media_list?: MediaItem[];
    mediaList?: MediaItem[];
}

/**
 * Media item attached to a message
 */
export interface MediaItem {
    id: number;
    url: string;
    type?: 'image' | 'video' | 'audio';
}

/**
 * User typing indicator
 */
export interface TypingEvent extends BaseEvent {
    type: 'typing';
    user: string;
    display_name?: string;
    display_initials?: string;
    conversation_id?: number;
}

/**
 * User stopped typing indicator
 */
export interface StoppedTypingEvent extends BaseEvent {
    type: 'stopped_typing';
    user: string;
    conversation_id?: number;
}

/**
 * Message status update (delivery/read receipts)
 */
export interface MessageStatusUpdateEvent extends BaseEvent {
    type: 'message.delivery.updated' | 'message_status_update';
    id: number;
    status: 'sent' | 'delivered' | 'failed';
    retryable?: boolean;
    error_code?: string;
    error_text?: string;
}

export interface SimulationStateChangedEvent extends BaseEvent {
    type: 'simulation.status.updated' | 'simulation.state_changed';
    simulation_id: number;
    status: 'in_progress' | 'completed' | 'timed_out' | 'failed' | 'canceled';
    terminal_reason_code?: string;
    terminal_reason_text?: string;
    retryable?: boolean;
}

export interface FeedbackFailedEvent extends BaseEvent {
    type: 'feedback.generation.failed' | 'feedback.failed';
    simulation_id: number;
    error_code?: string;
    error_text?: string;
    retryable?: boolean;
    retry_count?: number;
}

export interface FeedbackRetryingEvent extends BaseEvent {
    type: 'feedback.generation.updated' | 'feedback.retrying';
    simulation_id: number;
    status?: 'retrying';
    retryable?: boolean;
    retry_count?: number;
}

/**
 * Feedback created event
 */
export interface FeedbackCreatedEvent extends BaseEvent {
    type: 'feedback.item.created' | 'simulation.feedback_created' | 'feedback.created' | 'simulation.hotwash.created';
    tool?: string;
    html?: string;  // Optional server-rendered HTML for web clients
}

/**
 * Feedback continuation event
 */
export interface FeedbackContinuationEvent extends BaseEvent {
    type: 'simulation.feedback.continue_conversation' | 'simulation.hotwash.continue_conversation';
}

/**
 * Metadata results created event
 */
export interface MetadataResultsCreatedEvent extends BaseEvent {
    type: 'patient.results.updated' | 'simulation.metadata.results_created';
    tool?: string;
    html?: string;  // Optional server-rendered HTML for web clients
}

// ============================================================================
// TrainerLab Events
// ============================================================================

export interface TrainerLabDomainEventBase {
    simulation_id: number;
    domain_event_id?: number | null;
    domain_event_type?: string;
    source?: string;
    supersedes_event_id?: number | null;
    timestamp: string;
}

export interface TrainerLabCauseFields {
    id: number;
    active?: boolean;
    cause_kind: 'injury' | 'illness';
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    description?: string;
    anatomical_location?: string;
    laterality?: string;
    injury_location?: string;
    injury_kind?: string;
    injury_location_label?: string;
    injury_kind_label?: string;
    recommended_interventions?: TrainerLabRecommendedInterventionFields[];
    metadata?: Record<string, unknown>;
}

export interface InterventionDetailsBase {
    kind: string;
    version: number;
}

export interface TourniquetInterventionDetails extends InterventionDetailsBase {
    kind: 'tourniquet';
    version: 1;
    application_mode: 'hasty' | 'deliberate';
}

export interface WoundPackingInterventionDetails extends InterventionDetailsBase {
    kind: 'wound_packing';
    version: 1;
}

export interface PressureDressingInterventionDetails extends InterventionDetailsBase {
    kind: 'pressure_dressing';
    version: 1;
}

export interface NasopharyngealAirwayInterventionDetails extends InterventionDetailsBase {
    kind: 'npa';
    version: 1;
}

export interface OropharyngealAirwayInterventionDetails extends InterventionDetailsBase {
    kind: 'opa';
    version: 1;
}

export interface NeedleDecompressionInterventionDetails extends InterventionDetailsBase {
    kind: 'needle_decompression';
    version: 1;
}

export interface SurgicalCricInterventionDetails extends InterventionDetailsBase {
    kind: 'surgical_cric';
    version: 1;
}

export type InterventionDetails =
    | TourniquetInterventionDetails
    | WoundPackingInterventionDetails
    | PressureDressingInterventionDetails
    | NasopharyngealAirwayInterventionDetails
    | OropharyngealAirwayInterventionDetails
    | NeedleDecompressionInterventionDetails
    | SurgicalCricInterventionDetails;

export interface TrainerLabInterventionFields {
    intervention_id: number;
    active?: boolean;
    kind: string;
    code: string;
    title: string;
    intervention_label?: string;
    site_code?: string;
    site_label?: string;
    target_problem_id?: number | null;
    initiated_by_type: 'user' | 'instructor' | 'system';
    initiated_by_id?: number | null;
    status: string;
    effectiveness?: 'unknown' | 'effective' | 'partially_effective' | 'ineffective';
    clinical_effect?: string;
    target_problem_previous_status?: string;
    target_problem_current_status?: string;
    adjudication_reason?: string;
    adjudication_rule_id?: string;
    notes?: string;
    details?: InterventionDetails | Record<string, unknown>;
    description?: string;
}

export interface TrainerLabProblemFields {
    problem_id: number;
    active?: boolean;
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    description?: string;
    severity?: 'low' | 'moderate' | 'high' | 'critical';
    march_category?: string;
    march_category_label?: string;
    anatomical_location?: string;
    laterality?: string;
    status: 'active' | 'treated' | 'controlled' | 'resolved';
    previous_status?: string;
    treated_at?: string | null;
    controlled_at?: string | null;
    resolved_at?: string | null;
    cause_id: number;
    cause_kind: 'injury' | 'illness';
    parent_problem_id?: number | null;
    triggering_intervention_id?: number | null;
    adjudication_reason?: string;
    adjudication_rule_id?: string;
    recommended_interventions?: TrainerLabRecommendedInterventionFields[];
    metadata?: Record<string, unknown>;
}

export interface TrainerLabRecommendedInterventionFields {
    recommendation_id: number;
    active?: boolean;
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    description?: string;
    target_problem_id: number;
    target_cause_id?: number | null;
    target_cause_kind?: 'injury' | 'illness';
    recommendation_source: 'ai' | 'rules' | 'merged';
    validation_status: 'accepted' | 'normalized' | 'downgraded' | 'rejected';
    normalized_kind: string;
    normalized_code: string;
    rationale?: string;
    priority?: number | null;
    site_code?: string;
    site_label?: string;
    warnings?: string[];
    contraindications?: string[];
    metadata?: Record<string, unknown>;
}

export interface TrainerLabVitalFields {
    event_kind?: 'vital';
    vital_type: 'heart_rate' | 'respiratory_rate' | 'spo2' | 'etco2' | 'blood_glucose' | 'blood_pressure';
    min_value?: number;
    max_value?: number;
    lock_value?: boolean;
    min_value_diastolic?: number;
    max_value_diastolic?: number;
    trend?: 'up' | 'down' | 'stable' | 'variable';
}

export interface TrainerLabPulseFields {
    event_kind?: 'pulse_assessment';
    vital_type?: 'pulse_assessment';
    location: string;
    present: boolean;
    description: 'strong' | 'bounding' | 'weak' | 'absent' | 'thready';
    color_normal: boolean;
    color_description: 'pink' | 'pale' | 'mottled' | 'cyanotic' | 'flushed';
    condition_normal: boolean;
    condition_description: 'dry' | 'moist' | 'diaphoretic' | 'clammy';
    temperature_normal: boolean;
    temperature_description: 'warm' | 'cool' | 'cold' | 'hot';
}

export interface TrainerLabAssessmentFindingFields {
    finding_id: number;
    active?: boolean;
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    description?: string;
    status: 'present' | 'stable' | 'improving' | 'worsening';
    severity?: 'low' | 'moderate' | 'high' | 'critical';
    target_problem_id?: number | null;
    anatomical_location?: string;
    laterality?: string;
    metadata?: Record<string, unknown>;
}

export interface TrainerLabDiagnosticResultFields {
    diagnostic_id: number;
    active?: boolean;
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    description?: string;
    status: 'pending' | 'available' | 'reviewed';
    value_text?: string;
    target_problem_id?: number | null;
    metadata?: Record<string, unknown>;
}

export interface TrainerLabResourceFields {
    resource_id: number;
    active?: boolean;
    kind: string;
    code: string;
    slug?: string;
    title: string;
    display_name?: string;
    status: 'available' | 'limited' | 'depleted' | 'unavailable';
    quantity_available?: number;
    quantity_unit?: string;
    description?: string;
    metadata?: Record<string, unknown>;
}

export interface TrainerLabDispositionFields {
    disposition_id: number;
    active?: boolean;
    status: 'hold' | 'ready' | 'en_route' | 'delayed' | 'complete';
    transport_mode?: string;
    destination?: string;
    eta_minutes?: number | null;
    handoff_ready?: boolean;
    scene_constraints?: string[];
    metadata?: Record<string, unknown>;
}

export interface TrainerLabRecommendationEvaluationFields {
    evaluation_id: number;
    recommendation_id?: number | null;
    target_problem_id?: number | null;
    target_cause_id?: number | null;
    target_cause_kind?: 'injury' | 'illness';
    raw_kind?: string;
    raw_title?: string;
    raw_site?: string;
    normalized_kind?: string;
    normalized_code?: string;
    title?: string;
    recommendation_source: 'ai' | 'rules' | 'merged';
    validation_status: 'accepted' | 'normalized' | 'downgraded' | 'rejected';
    rationale?: string;
    priority?: number | null;
    warnings?: string[];
    contraindications?: string[];
    rejection_reason?: string;
    metadata?: Record<string, unknown>;
}

export interface TrainerLabPatientStatus {
    avpu?: string | null;
    respiratory_distress?: boolean;
    hemodynamic_instability?: boolean;
    impending_pneumothorax?: boolean;
    tension_pneumothorax?: boolean;
    narrative?: string;
    teaching_flags?: string[];
}

export interface TrainerLabAiIntent {
    summary?: string;
    rationale?: string;
    trigger?: string;
    eta_seconds?: number | null;
    confidence?: number;
    upcoming_changes?: string[];
    monitoring_focus?: string[];
}

export interface TrainerLabScenarioBriefFields {
    read_aloud_brief: string;
    environment?: string;
    location_overview?: string;
    threat_context?: string;
    evacuation_options?: string[];
    evacuation_time?: string;
    special_considerations?: string[];
}

export interface TrainerLabSnapshot {
    causes: TrainerLabCauseFields[];
    problems: TrainerLabProblemFields[];
    recommended_interventions: TrainerLabRecommendedInterventionFields[];
    interventions: TrainerLabInterventionFields[];
    assessment_findings: TrainerLabAssessmentFindingFields[];
    diagnostic_results: TrainerLabDiagnosticResultFields[];
    resources: TrainerLabResourceFields[];
    disposition?: TrainerLabDispositionFields | null;
    vitals: TrainerLabVitalFields[];
    pulses: TrainerLabPulseFields[];
    patient_status: TrainerLabPatientStatus;
    scenario_brief?: TrainerLabScenarioBriefFields | null;
}

export interface TrainerLabSnapshotCacheStatus {
    status: 'disabled' | 'missing' | 'stale' | 'available';
    authoritative: boolean;
    source?: string;
    state_revision?: number | null;
    legacy_keys_present?: string[];
}

export interface TrainerLabRuntimeSnapshot {
    status: string;
    phase?: string;
    state_revision: number;
    active_elapsed_seconds: number;
    tick_count?: number;
    tick_interval_seconds?: number;
    next_tick_at?: string | null;
    runtime_processing?: boolean;
    pending_runtime_reasons: Array<Record<string, unknown>>;
    currently_processing_reasons: Array<Record<string, unknown>>;
    ai_plan: TrainerLabAiIntent;
    ai_rationale_notes?: string[];
    llm_conditions_check?: Array<Record<string, unknown>>;
    last_runtime_error?: string;
    last_ai_tick_at?: string | null;
    last_runtime_enqueued_at?: string | null;
    last_runtime_completed_at?: string | null;
    control_plane_debug?: Record<string, unknown>;
    request_metadata?: Record<string, unknown>;
}

export interface TrainerLabStateMetadata {
    builder_version?: string;
    schema_version?: string;
    snapshot_cache: TrainerLabSnapshotCacheStatus;
    event_timeline_count?: number;
}

export interface TrainerLabInjuryCreatedEvent extends TrainerLabDomainEventBase, TrainerLabCauseFields {
    type: 'patient.injury.created' | 'patient.injury.updated' | 'injury.created' | 'injury.updated';
    event_kind: 'cause';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabIllnessCreatedEvent extends TrainerLabDomainEventBase, TrainerLabCauseFields {
    type: 'patient.illness.created' | 'patient.illness.updated' | 'illness.created' | 'illness.updated';
    event_kind: 'cause';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabProblemCreatedEvent extends TrainerLabDomainEventBase, TrainerLabProblemFields {
    type: 'patient.problem.created' | 'problem.created';
    event_kind: 'problem';
}

export interface TrainerLabProblemUpdatedEvent extends TrainerLabDomainEventBase, TrainerLabProblemFields {
    type: 'patient.problem.updated' | 'problem.updated' | 'problem.resolved';
    event_kind: 'problem';
}

export interface TrainerLabRecommendedInterventionEvent extends TrainerLabDomainEventBase, TrainerLabRecommendedInterventionFields {
    type: 'patient.recommendedintervention.created' | 'patient.recommendedintervention.updated' | 'patient.recommendedintervention.removed' | 'recommended_intervention.created' | 'recommended_intervention.updated' | 'recommended_intervention.removed';
    event_kind: 'recommended_intervention';
}

export interface TrainerLabPerformedInterventionEvent extends TrainerLabDomainEventBase, TrainerLabInterventionFields {
    type: 'patient.intervention.created' | 'patient.intervention.updated' | 'intervention.created' | 'intervention.updated';
    event_kind: 'intervention';
}

export interface TrainerLabVitalCreatedEvent extends TrainerLabDomainEventBase, TrainerLabVitalFields {
    type: 'patient.vital.created' | 'patient.vital.updated' | 'trainerlab.vital.created' | 'trainerlab.vital.updated';
    event_kind: 'vital';
}

export interface TrainerLabPulseEvent extends TrainerLabDomainEventBase, TrainerLabPulseFields {
    type: 'patient.pulse.created' | 'patient.pulse.updated' | 'trainerlab.pulse.created' | 'trainerlab.pulse.updated';
    event_kind: 'pulse_assessment';
}

export interface TrainerLabAssessmentFindingEvent extends TrainerLabDomainEventBase, TrainerLabAssessmentFindingFields {
    type: 'patient.assessmentfinding.created' | 'patient.assessmentfinding.updated' | 'patient.assessmentfinding.removed' | 'trainerlab.assessment_finding.created' | 'trainerlab.assessment_finding.updated' | 'trainerlab.assessment_finding.removed';
    event_kind: 'assessment_finding';
}

export interface TrainerLabDiagnosticResultEvent extends TrainerLabDomainEventBase, TrainerLabDiagnosticResultFields {
    type: 'patient.diagnosticresult.created' | 'patient.diagnosticresult.updated' | 'trainerlab.diagnostic_result.created' | 'trainerlab.diagnostic_result.updated';
    event_kind: 'diagnostic_result';
}

export interface TrainerLabResourceEvent extends TrainerLabDomainEventBase, TrainerLabResourceFields {
    type: 'patient.resource.updated' | 'trainerlab.resource.updated';
    event_kind: 'resource';
}

export interface TrainerLabDispositionEvent extends TrainerLabDomainEventBase, TrainerLabDispositionFields {
    type: 'patient.disposition.updated' | 'trainerlab.disposition.updated';
    event_kind: 'disposition';
}

export interface TrainerLabRecommendationEvaluationEvent extends TrainerLabDomainEventBase, TrainerLabRecommendationEvaluationFields {
    type: 'patient.recommendationevaluation.created' | 'trainerlab.recommendation_evaluation.created';
    event_kind: 'recommendation_evaluation';
}

export interface TrainerLabScenarioBriefEvent extends TrainerLabDomainEventBase, TrainerLabScenarioBriefFields {
    type: 'simulation.brief.created' | 'simulation.brief.updated' | 'trainerlab.scenario_brief.created' | 'trainerlab.scenario_brief.updated';
    event_kind: 'scenario_brief';
}

export interface TrainerLabNoteEvent extends TrainerLabDomainEventBase {
    type: 'simulation.note.created' | 'note.created';
    event_kind: 'note';
    content: string;
    created_by_role?: 'trainee' | 'instructor' | 'system';
}

export interface TrainerLabInterventionAssessedEvent extends BaseEvent {
    type: 'patient.intervention.updated' | 'trainerlab.intervention.assessed';
    intervention_id: number;
    intervention_type?: string | null;
    site_code?: string | null;
    effectiveness: 'unknown' | 'effective' | 'partially_effective' | 'ineffective';
    clinical_effect?: string;
    status: string;
    target_problem_id?: number | null;
    target_problem_title?: string | null;
    target_problem_status?: string | null;
}

export interface TrainerLabStateUpdatedEvent extends BaseEvent {
    type: 'simulation.snapshot.updated' | 'state.updated';
    simulation_id: number;
    session_id: number;
    status: string;
    scenario_snapshot: TrainerLabSnapshot;
    runtime_snapshot: TrainerLabRuntimeSnapshot;
    metadata?: TrainerLabStateMetadata;
    processed_reasons: Array<Record<string, unknown>>;
}

export interface TrainerLabAiIntentUpdatedEvent extends BaseEvent {
    type: 'simulation.plan.updated' | 'ai.intent.updated';
    simulation_id?: number;
    session_id?: number;
    status?: string;
    runtime_snapshot?: TrainerLabRuntimeSnapshot;
    metadata?: TrainerLabStateMetadata;
    ai_plan: TrainerLabAiIntent;
}

export interface TrainerLabRunLifecycleEvent extends BaseEvent {
    type: 'simulation.status.updated' | 'run.started' | 'run.paused' | 'run.resumed' | 'run.stopped' | 'session.seeded' | 'session.failed';
    status: string;
    from?: string;
    to?: string;
    discarded_runtime_reason_count?: number;
}

export interface TrainerLabRuntimeFailedEvent extends BaseEvent {
    type: 'simulation.runtime.failed' | 'runtime.failed';
    error: string;
    reasons: Array<Record<string, unknown>>;
}

export interface TrainerLabSummaryEvent extends BaseEvent {
    type: 'simulation.summary.updated' | 'summary.ready' | 'summary.updated';
    summary_id: number;
    status?: string;
    ai_debrief?: Record<string, unknown>;
    ai_debrief_revision?: number;
}

export interface TrainerLabSessionSeedingEvent extends BaseEvent {
    type: 'session.seeding';
    status: string;
    scenario_spec: Record<string, unknown>;
    state_revision: number;
    retry_count?: number;
}

export interface TrainerLabSessionSeededEvent extends BaseEvent {
    type: 'simulation.status.updated' | 'session.seeded';
    status: string;
    from?: string;
    to?: string;
    scenario_spec: Record<string, unknown>;
    state_revision: number;
}

export interface TrainerLabSessionFailedEvent extends BaseEvent {
    type: 'session.failed';
    status: string;
    reason_code: string;
    reason_text: string;
    retryable: boolean;
}

export interface TrainerLabSimplePayloadEvent extends BaseEvent {
    type:
        | 'simulation.annotation.created'
        | 'simulation.tick.triggered'
        | 'simulation.adjustment.updated'
        | 'simulation.preset.updated'
        | 'simulation.command.updated'
        | 'simulation.patch.completed'
        | 'trainerlab.annotation.created'
        | 'trainerlab.tick.triggered'
        | 'adjustment.accepted'
        | 'adjustment.applied'
        | 'preset.applied'
        | 'command.accepted';
    [key: string]: unknown;
}

// ============================================================================
// Union Type
// ============================================================================

/**
 * Any simulation event
 */
export type SimulationEvent =
    | ConnectedEvent
    | DisconnectedEvent
    | InitMessageEvent
    | ErrorEvent
    | ChatMessageCreatedEvent
    | TypingEvent
    | StoppedTypingEvent
    | MessageStatusUpdateEvent
    | SimulationStateChangedEvent
    | FeedbackFailedEvent
    | FeedbackRetryingEvent
    | FeedbackCreatedEvent
    | FeedbackContinuationEvent
    | MetadataResultsCreatedEvent
    | TrainerLabInjuryCreatedEvent
    | TrainerLabIllnessCreatedEvent
    | TrainerLabProblemCreatedEvent
    | TrainerLabProblemUpdatedEvent
    | TrainerLabRecommendedInterventionEvent
    | TrainerLabPerformedInterventionEvent
    | TrainerLabVitalCreatedEvent
    | TrainerLabPulseEvent
    | TrainerLabAssessmentFindingEvent
    | TrainerLabDiagnosticResultEvent
    | TrainerLabResourceEvent
    | TrainerLabDispositionEvent
    | TrainerLabRecommendationEvaluationEvent
    | TrainerLabScenarioBriefEvent
    | TrainerLabNoteEvent
    | TrainerLabInterventionAssessedEvent
    | TrainerLabStateUpdatedEvent
    | TrainerLabAiIntentUpdatedEvent
    | TrainerLabRunLifecycleEvent
    | TrainerLabRuntimeFailedEvent
    | TrainerLabSummaryEvent
    | TrainerLabSessionSeedingEvent
    | TrainerLabSessionSeededEvent
    | TrainerLabSessionFailedEvent
    | TrainerLabSimplePayloadEvent
    ;

// ============================================================================
// Client Commands (sent TO server)
// ============================================================================

/**
 * Commands sent from client to server via WebSocket
 */
export type ClientCommandType =
    | 'client_ready'
    | 'chat.message_created'
    | 'typing'
    | 'stopped_typing';

/**
 * Client ready command - sent on connection
 */
export interface ClientReadyCommand {
    type: 'client_ready';
    content_mode?: 'fullHtml' | 'rawText' | 'trigger';
}

/**
 * Send chat message command
 */
export interface SendMessageCommand {
    type: 'chat.message_created';
    content: string;
    role: 'user';
    status?: 'sent';
    conversation_id?: number;
}

/**
 * Typing indicator command
 */
export interface TypingCommand {
    type: 'typing';
    user: string;
    conversation_id?: number;
}

/**
 * Stopped typing command
 */
export interface StoppedTypingCommand {
    type: 'stopped_typing';
    user: string;
    conversation_id?: number;
}

/**
 * Any client command
 */
export type ClientCommand =
    | ClientReadyCommand
    | SendMessageCommand
    | TypingCommand
    | StoppedTypingCommand;
