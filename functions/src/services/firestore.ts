import * as admin from "firebase-admin";
import {StuffItem, TaskItem, EventItem, Item} from "../models/types.js";
import {ConversationDoc, ConversationMessage} from "../models/conversation.js";

const db = admin.firestore();
const itemsCol = db.collection("items");

// ==========================================
// ITEMS
// ==========================================

export async function createStuff(text: string): Promise<StuffItem> {
    const now = new Date().toISOString();
    const ref = itemsCol.doc();
    const stuff: StuffItem = {
        id: ref.id,
        type: "STUFF",
        text,
        status: "TODO",
        createdAt: now,
        updatedAt: now,
    };
    await ref.set(stuff);
    return stuff;
}

export async function getItem(itemId: string): Promise<Item> {
    const doc = await itemsCol.doc(itemId).get();
    if (!doc.exists) {
        throw new Error(`Item ${itemId} introuvable`);
    }
    return doc.data() as Item;
}

export async function markStuffDone(stuffId: string): Promise<void> {
    await itemsCol.doc(stuffId).update({
        status: "DONE",
        updatedAt: new Date().toISOString(),
    });
}

export async function createTaskItem(
    stuffId: string,
    stuffText: string,
    data: Record<string, unknown>,
): Promise<TaskItem> {
    const now = new Date().toISOString();
    const ref = itemsCol.doc();
    const task: TaskItem = {
        id: ref.id,
        type: "TASK",
        text: (data["text"] as string) || stuffText,
        status: "TODO",
        sourceStuffId: stuffId,
        category: (data["category"] as TaskItem["category"]) || "ACTION",
        context: (data["context"] as TaskItem["context"]) || "PERSONAL",
        priority: (data["priority"] as TaskItem["priority"]) || "MEDIUM",
        energyRequired: (data["energyRequired"] as TaskItem["energyRequired"]) || "MEDIUM",
        timeEstimate: (data["timeEstimate"] as number) ?? null,
        createdAt: now,
        updatedAt: now,
    };
    await ref.set(task);
    return task;
}

export async function createEventItem(
    stuffId: string,
    stuffText: string,
    data: Record<string, unknown>,
): Promise<EventItem> {
    const now = new Date().toISOString();
    const ref = itemsCol.doc();
    const event: EventItem = {
        id: ref.id,
        type: "EVENT",
        text: (data["text"] as string) || stuffText,
        status: "TODO",
        sourceStuffId: stuffId,
        context: (data["context"] as EventItem["context"]) || "PERSONAL",
        startDate: (data["startDate"] as string) || now.slice(0, 10),
        endDate: (data["endDate"] as string) || (data["startDate"] as string) || now.slice(0, 10),
        startTime: (data["startTime"] as string) ?? null,
        endTime: (data["endTime"] as string) ?? null,
        duration: (data["duration"] as number) ?? null,
        createdAt: now,
        updatedAt: now,
    };
    await ref.set(event);
    return event;
}

// ==========================================
// CONVERSATIONS
// ==========================================

function conversationRef(itemId: string, agent: string) {
    return itemsCol.doc(itemId).collection("conversations").doc(agent);
}

export async function getConversation(
    itemId: string,
    agent: string,
): Promise<ConversationDoc | null> {
    const doc = await conversationRef(itemId, agent).get();
    if (!doc.exists) return null;
    return doc.data() as ConversationDoc;
}

export async function createConversation(
    itemId: string,
    agent: string,
    stuffText: string,
): Promise<ConversationDoc> {
    const now = new Date().toISOString();
    const conv: ConversationDoc = {
        agent,
        status: "IN_PROGRESS",
        stuffText,
        messages: [],
        createdAt: now,
        updatedAt: now,
    };
    await conversationRef(itemId, agent).set(conv);
    return conv;
}

/**
 * Supprime les clés undefined d'un objet (Firestore n'accepte pas undefined).
 */
function stripUndefined<T extends Record<string, unknown>>(obj: T): T {
    return Object.fromEntries(
        Object.entries(obj).filter(([, v]) => v !== undefined),
    ) as T;
}

export async function addMessage(
    itemId: string,
    agent: string,
    message: ConversationMessage,
): Promise<void> {
    const ref = conversationRef(itemId, agent);
    const doc = await ref.get();
    const data = doc.data() as ConversationDoc | undefined;
    const messages = data?.messages ?? [];
    messages.push(stripUndefined(message as unknown as Record<string, unknown>) as unknown as ConversationMessage);
    await ref.update({
        messages,
        updatedAt: new Date().toISOString(),
    });
}

export async function findTodoStuff(): Promise<StuffItem | null> {
    const snapshot = await itemsCol
        .where("type", "==", "STUFF")
        .where("status", "==", "TODO")
        .orderBy("createdAt", "asc")
        .limit(1)
        .get();
    if (snapshot.empty) return null;
    return snapshot.docs[0].data() as StuffItem;
}

export async function completeConversation(
    itemId: string,
    agent: string,
): Promise<void> {
    await conversationRef(itemId, agent).update({
        status: "COMPLETED",
        updatedAt: new Date().toISOString(),
    });
}
