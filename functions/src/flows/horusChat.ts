import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {AgentResponseSchema, HorusLLMResponseSchema} from "../models/schemas.js";
import {ConversationMessage} from "../models/conversation.js";
import {buildHorusSystemPrompt} from "../prompts/horus.js";
import {
    findNextTodoTask,
    getItem,
    getConversation,
    createConversation,
    addMessage,
    completeConversation,
    markTaskDone,
    markTaskSkipped,
} from "../services/firestore.js";
import {StuffItem} from "../models/types.js";

const AGENT = "HORUS";

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
 * Exécute l'action retournée par Horus.
 */
async function executeHorusAction(
    action: string | undefined,
    taskId: string,
): Promise<void> {
    if (!action || action === "NONE") return;

    switch (action) {
    case "START_TIMER":
    case "STOP_TIMER":
        break;
    case "COMPLETE_TASK":
        await markTaskDone(taskId);
        break;
    case "SKIP_TASK":
        await markTaskSkipped(taskId);
        break;
    }
}

/**
 * Flow startHorus : Thoth lance Horus sur la prochaine tâche TODO.
 * Si une conversation Horus existe déjà pour cette tâche, il la reprend.
 */
export const startHorusChatFlow = ai.defineFlow(
    {
        name: "startHorusChat",
        outputSchema: AgentResponseSchema,
    },
    async () => {
        const task = await findNextTodoTask();
        if (!task) {
            return {
                agent: "THOTH",
                message: "Aucune tâche à exécuter pour le moment. Capture un stuff d'abord !",
                choices: ["Capturer une idée", "Revenir plus tard"],
                done: true,
            };
        }

        const stuff = await getItem(task.sourceStuffId) as StuffItem;

        let conv = await getConversation(task.id, AGENT);
        if (conv && conv.status === "COMPLETED") {
            return {
                agent: "THOTH",
                message: "Cette tâche a déjà été traitée.",
                choices: ["Voir la suivante", "Revenir plus tard"],
                done: true,
            };
        }
        if (!conv) {
            conv = await createConversation(task.id, AGENT, task.text);
        }

        if (conv.messages.length > 0) {
            const lastMessage = conv.messages[conv.messages.length - 1];
            if (lastMessage.role === "agent") {
                return {
                    agent: AGENT,
                    actionId: task.id,
                    title: task.text,
                    message: lastMessage.text,
                    choices: lastMessage.choices ?? ["Commencer", "Skip"],
                    done: false,
                };
            }
        }

        const systemPrompt = buildHorusSystemPrompt(task, stuff.text);
        const history = buildChatHistory(conv.messages);

        const userPrompt = conv.messages.length === 0
            ? `Voici la tâche à accomplir : "${task.text}". Propose-moi de commencer, skip ou reporter.`
            : "Continue la conversation.";

        const result = await ai.generate({
            model: DEFAULT_MODEL,
            system: systemPrompt,
            messages: history,
            prompt: userPrompt,
            output: {schema: HorusLLMResponseSchema},
        });

        const llmResponse = result.output;
        if (!llmResponse) {
            throw new Error("Horus n'a pas retourné de réponse structurée valide");
        }

        await executeHorusAction(llmResponse.action, task.id);

        if (llmResponse.action === "START_TIMER") {
            const agentMessage: ConversationMessage = {
                role: "agent",
                text: llmResponse.message,
                choices: ["Terminé", "Continuer plus tard", "Annuler"],
                timestamp: new Date().toISOString(),
            };
            await addMessage(task.id, AGENT, agentMessage);
            return {
                agent: AGENT,
                actionId: task.id,
                title: stuff.text,
                message: llmResponse.message,
                choices: ["Terminé", "Continuer plus tard", "Annuler"],
                done: false,
            };
        }

        const agentMessage: ConversationMessage = {
            role: "agent",
            text: llmResponse.message,
            choices: llmResponse.choices,
            timestamp: new Date().toISOString(),
        };
        await addMessage(task.id, AGENT, agentMessage);

        return {
            agent: AGENT,
            actionId: task.id,
            title: stuff.text,
            message: llmResponse.message,
            choices: llmResponse.choices,
            done: false,
        };
    },
);

/**
 * Flow answerHorus : L'utilisateur répond à une question d'Horus.
 */
export const answerHorusChatFlow = ai.defineFlow(
    {
        name: "answerHorusChat",
        inputSchema: AgentResponseSchema.pick({actionId: true}).extend({
            actionId: AgentResponseSchema.shape.actionId.unwrap(),
            answer: AgentResponseSchema.shape.message,
        }),
        outputSchema: AgentResponseSchema,
    },
    async (input) => {
        const taskId = input.actionId;
        const conv = await getConversation(taskId, AGENT);
        if (!conv) {
            throw new Error(`Aucune conversation Horus trouvée pour ${taskId}`);
        }
        if (conv.status === "COMPLETED") {
            throw new Error(`La conversation Horus pour ${taskId} est déjà terminée`);
        }

        const userMessage: ConversationMessage = {
            role: "user",
            text: input.answer,
            timestamp: new Date().toISOString(),
        };
        await addMessage(taskId, AGENT, userMessage);

        const task = await getItem(taskId);
        if (task.type !== "TASK") {
            throw new Error(`L'item ${taskId} n'est pas une tâche`);
        }
        const stuff = await getItem(task.sourceStuffId) as StuffItem;

        const fullMessages = [...conv.messages, userMessage];
        const history = buildChatHistory(fullMessages);
        const systemPrompt = buildHorusSystemPrompt(task, stuff.text);

        const result = await ai.generate({
            model: DEFAULT_MODEL,
            system: systemPrompt,
            messages: history,
            prompt: `L'utilisateur a répondu : "${input.answer}". Continue.`,
            output: {schema: HorusLLMResponseSchema},
        });

        const llmResponse = result.output;
        if (!llmResponse) {
            throw new Error("Horus n'a pas retourné de réponse structurée valide");
        }

        await executeHorusAction(llmResponse.action, taskId);

        if (llmResponse.action === "START_TIMER") {
            const agentMessage: ConversationMessage = {
                role: "agent",
                text: llmResponse.message,
                choices: ["Terminé", "Continuer plus tard", "Annuler"],
                timestamp: new Date().toISOString(),
            };
            await addMessage(taskId, AGENT, agentMessage);
            return {
                agent: AGENT,
                actionId: taskId,
                title: stuff.text,
                message: llmResponse.message,
                choices: ["Terminé", "Continuer plus tard", "Annuler"],
                done: false,
            };
        }

        const agentMessage: ConversationMessage = {
            role: "agent",
            text: llmResponse.message,
            choices: llmResponse.choices,
            timestamp: new Date().toISOString(),
        };
        await addMessage(taskId, AGENT, agentMessage);

        // Si tâche terminée ou skippée → done:true, Thoth re-routera
        if (llmResponse.action === "COMPLETE_TASK" || llmResponse.action === "SKIP_TASK") {
            await completeConversation(taskId, AGENT);
            return {
                agent: AGENT,
                title: stuff.text,
                message: llmResponse.message,
                done: true,
            };
        }

        return {
            agent: AGENT,
            actionId: taskId,
            title: stuff.text,
            message: llmResponse.message,
            choices: llmResponse.choices,
            done: false,
        };
    },
);
