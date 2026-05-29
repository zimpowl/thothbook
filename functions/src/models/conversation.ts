import {TaskItem, EventItem} from "./types.js";

// ==========================================
// TYPES DE CONVERSATION (Firestore + API)
// ==========================================

export type InputType =
    | "text_input"
    | "number_input"
    | "date_picker"
    | "time_picker"
    | "single_choice"
    | "yes_no";

export type ConversationStatus = "IN_PROGRESS" | "COMPLETED";

/**
 * Un message dans la conversation (stocké dans Firestore).
 */
export interface ConversationMessage {
    role: "agent" | "user";
    text: string;
    inputType?: InputType;   // Seulement pour role:"agent"
    choices?: string[];      // Seulement pour single_choice
    fieldKey?: string;       // Ex: "context", "priority"
    timestamp: string;       // ISO 8601
}

/**
 * Document Firestore : items/{itemId}/conversations/{agentId}
 */
export interface ConversationDoc {
    agent: string;
    status: ConversationStatus;
    stuffText: string;
    messages: ConversationMessage[];
    createdAt: string;
    updatedAt: string;
}

/**
 * Réponse API envoyée au client.
 */
export interface AgentResponse {
    agent: string;
    message: string;
    inputType: InputType;
    choices?: string[];
    fieldKey: string;
    done: boolean;
    createdItem?: TaskItem | EventItem;
}
