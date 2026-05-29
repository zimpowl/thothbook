import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AgentResponseSchema, AnubisLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {buildAnubisSystemPrompt} from "../prompts/anubis.js";
import {
    findTodoStuff,
    getConversation,
    createConversation,
    addMessage,
    getUserContexts,
    getUserListNames,
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
                choices: ["Capturer une idée", "Revenir plus tard"],
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
                choices: ["Voir le suivant", "Revenir plus tard"],
                done: true,
            };
        }

        // Créer la conversation si elle n'existe pas
        if (!conv) {
            conv = await createConversation(stuff.id, AGENT, stuff.text);
        }

        // Si le dernier message est de l'agent (pas encore de réponse user), le renvoyer directement
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

        // Sinon, appeler le LLM
        const [existingContexts, existingListNames] = await Promise.all([
            getUserContexts(),
            getUserListNames(),
        ]);
        const systemPrompt = buildAnubisSystemPrompt(existingContexts, existingListNames);
        const history = buildChatHistory(conv.messages);

        const userPrompt = conv.messages.length === 0
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

        // Sauvegarder le message d'Anubis dans la conversation
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
    },
);
