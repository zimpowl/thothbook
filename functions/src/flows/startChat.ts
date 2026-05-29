import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AgentResponseSchema, AnubisLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {buildAnubisSystemPrompt, ReviewContext} from "../prompts/anubis.js";
import {
    findTodoStuff,
    findStuffWaitingReview,
    findNextTodoTask,
    getItemsByStuffId,
    getConversation,
    createConversation,
    addMessage,
    getUserContexts,
    getUserListNames,
} from "../services/firestore.js";
import {resolveRoute} from "./thoth.js";
import {startHorusChatFlow} from "./horusChat.js";
import {StuffItem} from "../models/types.js";

/**
 * Construit l'historique de messages Genkit à partir de la conversation Firestore.
 */
function buildChatHistory(messages: ConversationMessage[]) {
    return messages.map((m) => ({
        role: m.role === "agent" ? "model" as const : "user" as const,
        content: [{text: m.text}],
    }));
}

/**
 * Construit le ReviewContext pour Anubis en mode review.
 */
async function buildReviewContext(stuff: StuffItem): Promise<ReviewContext> {
    const items = await getItemsByStuffId(stuff.id);
    return {
        stuffText: stuff.text,
        doneItems: items
            .filter((i) => i.status === "DONE")
            .map((i) => ({text: i.text, type: i.type})),
        pendingItems: items
            .filter((i) => i.status === "NOT_DONE")
            .map((i) => ({text: i.text, type: i.type})),
    };
}

/**
 * Lance Anubis sur un stuff (qualification ou review).
 */
async function startAnubisChat(stuff: StuffItem, mode: "qualification" | "review") {
    const AGENT = "ANUBIS";

    let conv = await getConversation(stuff.id, AGENT);
    if (conv && conv.status === "COMPLETED") {
        // En mode review, on crée une nouvelle conversation (nouveau tour)
        if (mode === "review") {
            conv = await createConversation(stuff.id, AGENT, stuff.text);
        } else {
            return {
                agent: "THOTH",
                message: "Ce stuff a déjà été traité.",
                choices: ["Voir le suivant", "Revenir plus tard"],
                done: true,
            };
        }
    }
    if (!conv) {
        conv = await createConversation(stuff.id, AGENT, stuff.text);
    }

    // Si le dernier message est de l'agent, le renvoyer
    if (conv.messages.length > 0) {
        const lastMessage = conv.messages[conv.messages.length - 1];
        if (lastMessage.role === "agent") {
            return {
                agent: AGENT,
                actionId: stuff.id,
                title: stuff.text,
                message: lastMessage.text,
                choices: lastMessage.choices ?? ["Oui", "Non"],
                done: false,
            };
        }
    }

    // Construire le prompt
    const [existingContexts, existingListNames] = await Promise.all([
        getUserContexts(),
        getUserListNames(),
    ]);

    let reviewCtx: ReviewContext | undefined;
    if (mode === "review") {
        reviewCtx = await buildReviewContext(stuff);
    }

    const systemPrompt = buildAnubisSystemPrompt(existingContexts, existingListNames, reviewCtx);
    const history = buildChatHistory(conv.messages);

    const userPrompt = mode === "review"
        ? `Les tâches liées à l'objectif "${stuff.text}" sont terminées. Vérifie si l'objectif est atteint ou s'il faut une nouvelle action.`
        : conv.messages.length === 0
            ? `Voici l'idée brute à qualifier : "${stuff.text}"`
            : "Continue la conversation. Pose la prochaine question.";

    const result = await ai.generate({
        model: DEFAULT_MODEL,
        system: systemPrompt,
        messages: history,
        prompt: userPrompt,
        output: {schema: AnubisLLMResponseSchema},
    });

    const llmResponse = result.output;
    if (!llmResponse) {
        throw new Error("Anubis n'a pas retourné de réponse structurée valide");
    }

    const agentMessage: ConversationMessage = {
        role: "agent",
        text: llmResponse.message,
        choices: llmResponse.choices,
        timestamp: new Date().toISOString(),
    };
    await addMessage(stuff.id, AGENT, agentMessage);

    return {
        agent: AGENT,
        actionId: stuff.id,
        title: stuff.text,
        message: llmResponse.message,
        choices: llmResponse.choices,
        done: false,
    };
}

/**
 * Flow startChat : GET sans paramètres.
 * Thoth route par priorité : stuff TODO → Anubis, stuff WAIT review → Anubis, tâche TODO → Horus.
 */
export const startChatFlow = ai.defineFlow(
    {
        name: "startChat",
        outputSchema: AgentResponseSchema,
    },
    async () => {
        // Collecter les infos pour le routing
        const stuff = await findTodoStuff();
        const waitingStuff = !stuff ? await findStuffWaitingReview() : null;
        const task = !stuff && !waitingStuff ? await findNextTodoTask() : null;

        const route = resolveRoute({
            hasTodoStuff: !!stuff,
            waitingReviewStuffId: waitingStuff?.id,
            hasTodoTask: !!task,
        });

        // Route vers l'agent approprié
        if (route.agent === "ANUBIS" && route.mode === "qualification" && stuff) {
            return startAnubisChat(stuff, "qualification");
        }

        if (route.agent === "ANUBIS" && route.mode === "review" && waitingStuff) {
            return startAnubisChat(waitingStuff, "review");
        }

        if (route.agent === "HORUS") {
            if (task) {
                return startHorusChatFlow();
            }
            return {
                agent: "THOTH",
                message: "Aucune idée à traiter et aucune tâche en attente. Capture un stuff d'abord !",
                choices: ["Capturer une idée", "Revenir plus tard"],
                done: true,
            };
        }

        return {
            agent: "THOTH",
            message: "Aucune idée à traiter et aucune tâche en attente. Capture un stuff d'abord !",
            choices: ["Capturer une idée", "Revenir plus tard"],
            done: true,
        };
    },
);
