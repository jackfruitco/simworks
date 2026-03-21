/**
 * WebSocket Event Schema for SimWorks Simulations
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
// common Event Types
// ============================================================================

/**
 * All possible simulation event types
 */
export type SimulationEventType =
    // Connection events (dispatched by SimulationSocket, not from server)
    | 'connected'
    | 'disconnected'

    // Initialization
    | 'init_message'
    | 'error'

    // Chat events
    | 'chat.message_created'
    | 'typing'
    | 'stopped_typing'
    | 'message_status_update'

    // Simulation state events
    | 'simulation.feedback_created'
    | 'feedback.created'
    | 'simulation.hotwash.created'
    | 'simulation.feedback.continue_conversation'
    | 'simulation.hotwash.continue_conversation'
    | 'simulation.metadata.results_created'
    | 'simulation.state_changed'
    | 'feedback.failed'
    | 'feedback.retrying'

    // TrainerLab events
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
    | 'command.accepted';

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
    type: 'chat.message_created';
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
    type: 'message_status_update';
    id: number;
    status: 'sent' | 'delivered' | 'failed';
    retryable?: boolean;
    error_code?: string;
    error_text?: string;
}

export interface SimulationStateChangedEvent extends BaseEvent {
    type: 'simulation.state_changed';
    simulation_id: number;
    status: 'in_progress' | 'completed' | 'timed_out' | 'failed' | 'canceled';
    terminal_reason_code?: string;
    terminal_reason_text?: string;
    retryable?: boolean;
}

export interface FeedbackFailedEvent extends BaseEvent {
    type: 'feedback.failed';
    simulation_id: number;
    error_code?: string;
    error_text?: string;
    retryable?: boolean;
    retry_count?: number;
}

export interface FeedbackRetryingEvent extends BaseEvent {
    type: 'feedback.retrying';
    simulation_id: number;
    retryable?: boolean;
    retry_count?: number;
}

/**
 * Feedback created event
 */
export interface FeedbackCreatedEvent extends BaseEvent {
    type: 'simulation.feedback_created' | 'feedback.created' | 'simulation.hotwash.created';
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
    type: 'simulation.metadata.results_created';
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

export interface TrainerLabInjuryCreatedEvent extends TrainerLabDomainEventBase, TrainerLabCauseFields {
    type: 'injury.created' | 'injury.updated';
    event_kind: 'cause';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabIllnessCreatedEvent extends TrainerLabDomainEventBase, TrainerLabCauseFields {
    type: 'illness.created' | 'illness.updated';
    event_kind: 'cause';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabProblemCreatedEvent extends TrainerLabDomainEventBase, TrainerLabProblemFields {
    type: 'problem.created';
    event_kind: 'problem';
}

export interface TrainerLabProblemUpdatedEvent extends TrainerLabDomainEventBase, TrainerLabProblemFields {
    type: 'problem.updated' | 'problem.resolved';
    event_kind: 'problem';
}

export interface TrainerLabRecommendedInterventionEvent extends TrainerLabDomainEventBase, TrainerLabRecommendedInterventionFields {
    type: 'recommended_intervention.created' | 'recommended_intervention.updated' | 'recommended_intervention.removed';
    event_kind: 'recommended_intervention';
}

export interface TrainerLabPerformedInterventionEvent extends TrainerLabDomainEventBase, TrainerLabInterventionFields {
    type: 'intervention.created' | 'intervention.updated';
    event_kind: 'intervention';
}

export interface TrainerLabVitalCreatedEvent extends TrainerLabDomainEventBase, TrainerLabVitalFields {
    type: 'trainerlab.vital.created' | 'trainerlab.vital.updated';
    event_kind: 'vital';
}

export interface TrainerLabPulseEvent extends TrainerLabDomainEventBase, TrainerLabPulseFields {
    type: 'trainerlab.pulse.created' | 'trainerlab.pulse.updated';
    event_kind: 'pulse_assessment';
}

export interface TrainerLabAssessmentFindingEvent extends TrainerLabDomainEventBase, TrainerLabAssessmentFindingFields {
    type: 'trainerlab.assessment_finding.created' | 'trainerlab.assessment_finding.updated' | 'trainerlab.assessment_finding.removed';
    event_kind: 'assessment_finding';
}

export interface TrainerLabDiagnosticResultEvent extends TrainerLabDomainEventBase, TrainerLabDiagnosticResultFields {
    type: 'trainerlab.diagnostic_result.created' | 'trainerlab.diagnostic_result.updated';
    event_kind: 'diagnostic_result';
}

export interface TrainerLabResourceEvent extends TrainerLabDomainEventBase, TrainerLabResourceFields {
    type: 'trainerlab.resource.updated';
    event_kind: 'resource';
}

export interface TrainerLabDispositionEvent extends TrainerLabDomainEventBase, TrainerLabDispositionFields {
    type: 'trainerlab.disposition.updated';
    event_kind: 'disposition';
}

export interface TrainerLabRecommendationEvaluationEvent extends TrainerLabDomainEventBase, TrainerLabRecommendationEvaluationFields {
    type: 'trainerlab.recommendation_evaluation.created';
    event_kind: 'recommendation_evaluation';
}

export interface TrainerLabScenarioBriefEvent extends TrainerLabDomainEventBase, TrainerLabScenarioBriefFields {
    type: 'trainerlab.scenario_brief.created' | 'trainerlab.scenario_brief.updated';
    event_kind: 'scenario_brief';
}

export interface TrainerLabNoteEvent extends TrainerLabDomainEventBase {
    type: 'note.created';
    event_kind: 'note';
    content: string;
    created_by_role?: 'trainee' | 'instructor' | 'system';
}

export interface TrainerLabInterventionAssessedEvent extends BaseEvent {
    type: 'trainerlab.intervention.assessed';
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
    type: 'state.updated';
    state_revision: number;
    active_elapsed_seconds: number;
    scenario_brief?: TrainerLabScenarioBriefFields | null;
    current_snapshot: TrainerLabSnapshot;
    processed_reasons: Array<Record<string, unknown>>;
}

export interface TrainerLabAiIntentUpdatedEvent extends BaseEvent {
    type: 'ai.intent.updated';
    state_revision: number;
    ai_plan: TrainerLabAiIntent;
}

export interface TrainerLabRunLifecycleEvent extends BaseEvent {
    type: 'run.started' | 'run.paused' | 'run.resumed' | 'run.stopped';
    status: string;
    discarded_runtime_reason_count?: number;
}

export interface TrainerLabRuntimeFailedEvent extends BaseEvent {
    type: 'runtime.failed';
    error: string;
    reasons: Array<Record<string, unknown>>;
}

export interface TrainerLabSummaryEvent extends BaseEvent {
    type: 'summary.ready' | 'summary.updated';
    summary_id: number;
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
    type: 'session.seeded';
    status: string;
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
