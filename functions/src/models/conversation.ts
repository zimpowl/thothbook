// ==========================================
// TYPES DE CONVERSATION (Firestore + API)
// ==========================================

export type ConversationStatus = "IN_PROGRESS" | "COMPLETED";

/**
 * Un message dans la conversation (stocké dans Firestore).
 */
export interface ConversationMessage {
    role: "agent" | "user";
    text: string;
    choices?: string[];      // Toujours 2-4 choix pour role:"agent"
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
