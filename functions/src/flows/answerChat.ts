import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AnswerClarifyInputSchema, AgentResponseSchema, AnubisLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {buildAnubisSystemPrompt, ReviewContext} from "../prompts/anubis.js";
import {
    getItem,
    getItemsByStuffId,
    getConversation,
    addMessage,
    completeConversation,
    markStuffDone,
    markStuffWait,
    createTaskItem,
    createEventItem,
    createListItem,
    getUserContexts,
    getUserListNames,
} from "../services/firestore.js";
import {answerHorusChatFlow} from "./horusChat.js";
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
 * Flow answerChat : L'utilisateur répond à une question.
 * Route vers Anubis ou Horus selon la conversation existante.
 */
export const answerChatFlow = ai.defineFlow(
    {
        name: "answerChat",
        inputSchema: AnswerClarifyInputSchema,
        outputSchema: AgentResponseSchema,
    },
    async (input) => {
        // Vérifier si c'est une conversation Horus
        const horusConv = await getConversation(input.actionId, "HORUS");
        if (horusConv && horusConv.status !== "COMPLETED") {
            return answerHorusChatFlow({actionId: input.actionId, answer: input.answer});
        }

        // --- ANUBIS ---
        const AGENT = "ANUBIS";
        const conv = await getConversation(input.actionId, AGENT);
        if (!conv) {
            throw new Error(`Aucune conversation trouvée pour ${input.actionId}`);
        }
        if (conv.status === "COMPLETED") {
            throw new Error(`La clarification pour ${input.actionId} est déjà terminée`);
        }

        // Déterminer le mode : le stuff est en WAIT → review, sinon → qualification
        const stuff = await getItem(input.actionId) as StuffItem;
        const isReviewMode = stuff.status === "WAIT";

        // Sauvegarder la réponse de l'utilisateur
        const userMessage: ConversationMessage = {
            role: "user",
            text: input.answer,
            timestamp: new Date().toISOString(),
        };
        await addMessage(input.actionId, AGENT, userMessage);

        // Construire l'historique complet
        const fullMessages = [...conv.messages, userMessage];
        const history = buildChatHistory(fullMessages);

        // Récupérer contextes et listes existants
        const [existingContexts, existingListNames] = await Promise.all([
            getUserContexts(),
            getUserListNames(),
        ]);

        let reviewCtx: ReviewContext | undefined;
        if (isReviewMode) {
            reviewCtx = await buildReviewContext(stuff);
        }

        const systemPrompt = buildAnubisSystemPrompt(existingContexts, existingListNames, reviewCtx);

        // Appeler le LLM avec tout l'historique
        const result = await ai.generate({
            model: DEFAULT_MODEL,
            system: systemPrompt,
            messages: history,
            prompt: `L'utilisateur a répondu : "${input.answer}". Continue la qualification.`,
            output: {schema: AnubisLLMResponseSchema},
        });

        const llmResponse = result.output;
        if (!llmResponse) {
            throw new Error("Anubis n'a pas retourné de réponse structurée valide");
        }

        // Sauvegarder le message d'Anubis
        const agentMessage: ConversationMessage = {
            role: "agent",
            text: llmResponse.message,
            choices: llmResponse.choices,
            timestamp: new Date().toISOString(),
        };
        await addMessage(input.actionId, AGENT, agentMessage);

        // Si Anubis a terminé
        if (llmResponse.done) {
            // Mode review : closeStuff → stuff DONE, sinon crée un nouvel item
            if (isReviewMode && llmResponse.closeStuff) {
                await markStuffDone(input.actionId);
                await completeConversation(input.actionId, AGENT);
                return {
                    agent: AGENT,
                    title: conv.stuffText,
                    message: llmResponse.message,
                    done: true,
                };
            }

            // Créer l'item (qualification ou review avec nouvelle action)
            if (llmResponse.itemType && llmResponse.item) {
                const itemData = llmResponse.item as Record<string, unknown>;

                let createdItem;
                if (llmResponse.itemType === "TASK") {
                    createdItem = await createTaskItem(input.actionId, conv.stuffText, itemData);
                } else if (llmResponse.itemType === "LIST") {
                    createdItem = await createListItem(input.actionId, conv.stuffText, itemData);
                } else {
                    createdItem = await createEventItem(input.actionId, conv.stuffText, itemData);
                }

                // Mode qualification → stuff passe en WAIT
                // Mode review → stuff reste en WAIT (nouvelle tâche créée)
                if (!isReviewMode) {
                    await markStuffWait(input.actionId);
                }
                await completeConversation(input.actionId, AGENT);

                return {
                    agent: AGENT,
                    title: conv.stuffText,
                    message: llmResponse.message,
                    done: true,
                    createdItem: createdItem as unknown as Record<string, unknown>,
                };
            }
        }

        return {
            agent: AGENT,
            title: conv.stuffText,
            message: llmResponse.message,
            choices: llmResponse.choices,
            done: false,
        };
    },
);
