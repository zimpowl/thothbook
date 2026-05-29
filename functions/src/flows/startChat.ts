import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AgentResponseSchema, AnubisLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {ANUBIS_SYSTEM_PROMPT} from "../prompts/anubis.js";
import {
    findTodoStuff,
    getConversation,
    createConversation,
    addMessage,
} from "../services/firestore.js";
import {routeStuff} from "./thoth.js";

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
 * Flow startChat : GET sans paramètres.
 * Thoth cherche un stuff TODO et lance Anubis dessus.
 * Si une conversation est déjà en cours, il la reprend.
 */
export const startChatFlow = ai.defineFlow(
    {
        name: "startChat",
        outputSchema: AgentResponseSchema,
    },
    async () => {
        // Thoth cherche le prochain stuff à traiter
        const stuff = await findTodoStuff();
        if (!stuff) {
            return {
                agent: "THOTH",
                message: "Aucune idée à traiter pour le moment. Capture un stuff d'abord !",
                inputType: "text_input" as const,
                fieldKey: "info",
                done: true,
            };
        }

        // Thoth route vers l'agent approprié
        const agent = routeStuff(stuff.status);
        if (agent !== AGENT) {
            throw new Error(`Agent ${agent} non supporté pour l'instant`);
        }

        // Vérifier s'il existe une conversation en cours (reprise)
        let conv = await getConversation(stuff.id, AGENT);
        if (conv && conv.status === "COMPLETED") {
            // Ce stuff est déjà traité, on ne devrait pas arriver ici
            return {
                agent: "THOTH",
                message: "Ce stuff a déjà été traité.",
                inputType: "text_input" as const,
                fieldKey: "info",
                done: true,
            };
        }

        // Créer la conversation si elle n'existe pas
        if (!conv) {
            conv = await createConversation(stuff.id, AGENT, stuff.text);
        }

        // Si la conversation a déjà des messages, reprendre
        const history = buildChatHistory(conv.messages);

        // Appeler le LLM
        const userPrompt = conv.messages.length === 0
            ? `Voici l'idée brute à qualifier : "${stuff.text}"`
            : "Continue la conversation. Pose la prochaine question.";

        const result = await ai.generate({
            model: DEFAULT_MODEL,
            system: ANUBIS_SYSTEM_PROMPT,
            messages: history,
            prompt: userPrompt,
            output: {schema: AnubisLLMResponseSchema},
        });

        const llmResponse = result.output;
        if (!llmResponse) {
            throw new Error("Anubis n'a pas retourné de réponse structurée valide");
        }

        // Sauvegarder le message d'Anubis dans la conversation
        const agentMessage: ConversationMessage = {
            role: "agent",
            text: llmResponse.message,
            inputType: llmResponse.inputType,
            choices: llmResponse.choices,
            fieldKey: llmResponse.fieldKey,
            timestamp: new Date().toISOString(),
        };
        await addMessage(stuff.id, AGENT, agentMessage);

        return {
            agent: AGENT,
            stuffId: stuff.id,
            message: llmResponse.message,
            inputType: llmResponse.inputType,
            choices: llmResponse.choices,
            fieldKey: llmResponse.fieldKey,
            done: false,
        };
    },
);
