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
    | 'simulation.hotwash.created'
    | 'simulation.feedback.continue_conversation'
    | 'simulation.hotwash.continue_conversation'
    | 'simulation.metadata.results_created'

    // TrainerLab events (future)
    | 'vitals.updated'
    | 'injury.created'
    | 'intervention.created';

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
}

/**
 * User stopped typing indicator
 */
export interface StoppedTypingEvent extends BaseEvent {
    type: 'stopped_typing';
    user: string;
}

/**
 * Message status update (delivery/read receipts)
 */
export interface MessageStatusUpdateEvent extends BaseEvent {
    type: 'message_status_update';
    id: number;
    status: 'delivered' | 'read';
}

/**
 * Feedback created event
 */
export interface FeedbackCreatedEvent extends BaseEvent {
    type: 'simulation.feedback_created' | 'simulation.hotwash.created';
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
// TrainerLab Events (Future)
// ============================================================================

/**
 * Vital signs updated event
 */
export interface VitalsUpdatedEvent extends BaseEvent {
    type: 'vitals.updated';
    simulation_id: number;
    vital_type: 'heart_rate' | 'spo2' | 'etco2' | 'blood_glucose' | 'blood_pressure';
    value: number;
    min_value?: number;
    max_value?: number;
    timestamp: string;
}

/**
 * Injury created event
 */
export interface InjuryCreatedEvent extends BaseEvent {
    type: 'injury.created';
    simulation_id: number;
    injury_id: number;
    category: string;
    location: string;
    kind: string;
    description?: string;
}

/**
 * Intervention created event
 */
export interface InterventionCreatedEvent extends BaseEvent {
    type: 'intervention.created';
    simulation_id: number;
    intervention_id: number;
    intervention_type: string;
    description?: string;
    timestamp: string;
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
    | FeedbackCreatedEvent
    | FeedbackContinuationEvent
    | MetadataResultsCreatedEvent
    | VitalsUpdatedEvent
    | InjuryCreatedEvent
    | InterventionCreatedEvent;

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
}

/**
 * Stopped typing command
 */
export interface StoppedTypingCommand {
    type: 'stopped_typing';
    user: string;
}

/**
 * Any client command
 */
export type ClientCommand =
    | ClientReadyCommand
    | SendMessageCommand
    | TypingCommand
    | StoppedTypingCommand;
