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
    | 'trainerlab.condition.created'
    | 'trainerlab.vital.created'
    | 'trainerlab.event.created';

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

export interface TrainerLabInjuryFields {
    injury_id: number;
    parent_injury_id?: number | null;
    injury_category: string;
    injury_location: string;
    injury_kind: string;
    injury_description?: string;
    is_treated?: boolean;
    is_resolved?: boolean;
    injury_category_label?: string;
    injury_location_label?: string;
    injury_kind_label?: string;
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
    intervention_type: string;
    intervention_label?: string;
    site_code: string;
    site_label?: string;
    target_injury_id?: number | null;
    status: 'applied' | 'adjusted' | 'reassessed' | 'removed';
    effectiveness: 'unknown' | 'effective' | 'partially_effective' | 'ineffective';
    notes?: string;
    details: InterventionDetails;
}

export interface TrainerLabIllnessFields {
    illness_id: number;
    name: string;
    description?: string;
    severity: 'low' | 'moderate' | 'high' | 'critical';
    is_resolved?: boolean;
}

export interface TrainerLabVitalFields {
    event_kind?: 'vital';
    vital_type: 'heart_rate' | 'respiratory_rate' | 'spo2' | 'etco2' | 'blood_glucose' | 'blood_pressure';
    min_value?: number;
    max_value?: number;
    lock_value?: boolean;
    min_value_diastolic?: number;
    max_value_diastolic?: number;
}

export interface TrainerLabConditionCreatedInjuryEvent extends TrainerLabDomainEventBase, TrainerLabInjuryFields {
    type: 'trainerlab.condition.created';
    event_kind: 'injury';
    condition_kind: 'injury';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabConditionCreatedIllnessEvent extends TrainerLabDomainEventBase, TrainerLabIllnessFields {
    type: 'trainerlab.condition.created';
    event_kind: 'illness';
    condition_kind: 'illness';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabVitalCreatedEvent extends TrainerLabDomainEventBase, TrainerLabVitalFields {
    type: 'trainerlab.vital.created';
    event_kind: 'vital';
    origin?: string;
    call_id?: string;
    correlation_id?: string | null;
}

export interface TrainerLabEventCreatedInjuryEvent extends TrainerLabDomainEventBase, TrainerLabInjuryFields {
    type: 'trainerlab.event.created';
    event_kind: 'injury';
}

export interface TrainerLabEventCreatedIllnessEvent extends TrainerLabDomainEventBase, TrainerLabIllnessFields {
    type: 'trainerlab.event.created';
    event_kind: 'illness';
}

export interface TrainerLabEventCreatedInterventionEvent extends TrainerLabDomainEventBase, TrainerLabInterventionFields {
    type: 'trainerlab.event.created';
    event_kind: 'intervention';
}

export interface TrainerLabEventCreatedVitalEvent extends TrainerLabDomainEventBase, TrainerLabVitalFields {
    type: 'trainerlab.event.created';
    event_kind: 'vital';
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
    | TrainerLabConditionCreatedInjuryEvent
    | TrainerLabConditionCreatedIllnessEvent
    | TrainerLabVitalCreatedEvent
    | TrainerLabEventCreatedInjuryEvent
    | TrainerLabEventCreatedIllnessEvent
    | TrainerLabEventCreatedInterventionEvent
    | TrainerLabEventCreatedVitalEvent;

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
