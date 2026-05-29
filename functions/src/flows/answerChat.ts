import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AnswerClarifyInputSchema, AgentResponseSchema, AnubisLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {ANUBIS_SYSTEM_PROMPT} from "../prompts/anubis.js";
import {
    getConversation,
    addMessage,
    completeConversation,
    markStuffDone,
    createTaskItem,
    createEventItem,
} from "../services/firestore.js";

const AGENT = "ANUBIS";

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
 * Flow answerChat : L'utilisateur répond à une question d'Anubis.
 */
export const answerChatFlow = ai.defineFlow(
    {
        name: "answerChat",
        inputSchema: AnswerClarifyInputSchema,
        outputSchema: AgentResponseSchema,
    },
    async (input) => {
        const conv = await getConversation(input.actionId, AGENT);
        if (!conv) {
            throw new Error(`Aucune conversation trouvée pour ${input.actionId}`);
        }
        if (conv.status === "COMPLETED") {
            throw new Error(`La clarification pour ${input.actionId} est déjà terminée`);
        }

        // Sauvegarder la réponse de l'utilisateur
        const userMessage: ConversationMessage = {
            role: "user",
            text: input.answer,
            timestamp: new Date().toISOString(),
        };
        await addMessage(input.actionId, AGENT, userMessage);

        // Construire l'historique complet (incluant la nouvelle réponse)
        const fullMessages = [...conv.messages, userMessage];
        const history = buildChatHistory(fullMessages);

        // Appeler le LLM avec tout l'historique
        const result = await ai.generate({
            model: DEFAULT_MODEL,
            system: ANUBIS_SYSTEM_PROMPT,
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
            inputType: llmResponse.inputType,
            choices: llmResponse.choices,
            fieldKey: llmResponse.fieldKey,
            timestamp: new Date().toISOString(),
        };
        await addMessage(input.actionId, AGENT, agentMessage);

        // Si Anubis a terminé, créer l'item et finaliser
        if (llmResponse.done && llmResponse.itemType && llmResponse.item) {
            const itemData = llmResponse.item as Record<string, unknown>;

            let createdItem;
            if (llmResponse.itemType === "TASK") {
                createdItem = await createTaskItem(input.actionId, conv.stuffText, itemData);
            } else {
                createdItem = await createEventItem(input.actionId, conv.stuffText, itemData);
            }

            // Marquer le stuff comme DONE et la conversation comme COMPLETED
            await markStuffDone(input.actionId);
            await completeConversation(input.actionId, AGENT);

            return {
                agent: AGENT,
                title: conv.stuffText,
                message: llmResponse.message,
                inputType: llmResponse.inputType,
                fieldKey: llmResponse.fieldKey,
                done: true,
                createdItem: createdItem as unknown as Record<string, unknown>,
            };
        }

        return {
            agent: AGENT,
            title: conv.stuffText,
            message: llmResponse.message,
            inputType: llmResponse.inputType,
            choices: llmResponse.choices,
            fieldKey: llmResponse.fieldKey,
            done: false,
        };
    },
);
