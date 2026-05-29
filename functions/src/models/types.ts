// ==========================================
// 1. TYPES ET ENUMS DE BASE (FIRESTORE)
// ==========================================

export type ItemType = "STUFF" | "TASK" | "EVENT";
export type ItemStatus = "TODO" | "WAIT" | "DONE" | "NOT_DONE";
export type Priority = "LOW" | "MEDIUM" | "HIGH";
export type EnergyLevel = "LOW" | "MEDIUM" | "HIGH";
export type ItemContext = "WORK" | "PERSONAL" | "HEALTH" | "LEISURE";
export type TaskCategory = "ACTION" | "DELEGATE" | "ONE_DAY" | "REFERENCE";

// ==========================================
// 2. MODÈLES DE DONNÉES FIRESTORE
// ==========================================

/**
 * Interface de base pour tous les éléments de la collection "items".
 */
interface BaseItem {
    id: string;
    type: ItemType;
    text: string;
    status: ItemStatus;
    createdAt: string; // ISO 8601
    updatedAt: string; // ISO 8601
}

/**
 * État initial : L'idée brute déposée rapidement (Capture GTD).
 */
export interface StuffItem extends BaseItem {
    type: "STUFF";
}

/**
 * Une Tâche qualifiée par Anubis, sans contrainte temporelle fixe.
 */
export interface TaskItem extends BaseItem {
    type: "TASK";
    sourceStuffId: string;
    category: TaskCategory;
    context: ItemContext;
    priority: Priority;
    energyRequired: EnergyLevel;
    timeEstimate: number | null; // Durée estimée en minutes
}

/**
 * Un Événement qualifié par Anubis, ancré dans le calendrier.
 */
export interface EventItem extends BaseItem {
    type: "EVENT";
    sourceStuffId: string;
    context: ItemContext;
    startDate: string;         // YYYY-MM-DD
    endDate: string;           // YYYY-MM-DD
    startTime: string | null;  // HH:MM ou null = toute la journée
    endTime: string | null;
    duration: number | null;   // Minutes
}

/**
 * Type d'union pour la collection "items"
 */
export type Item = StuffItem | TaskItem | EventItem;
