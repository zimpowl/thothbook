import {z} from "zod";

// ==========================================
// SCHÉMAS ZOD POUR VALIDATION GENKIT
// ==========================================

// --- Schémas d'entrée des flows ---

export const CaptureStuffInputSchema = z.object({
    text: z.string().min(1, "Le texte ne peut pas être vide"),
});

export const StartClarifyInputSchema = z.object({
    stuffId: z.string().min(1),
});

export const AnswerClarifyInputSchema = z.object({
    actionId: z.string().min(1),
    answer: z.string().min(1, "La réponse ne peut pas être vide"),
});

// --- Schémas de sortie des flows ---

export const CaptureStuffOutputSchema = z.object({
    stuffId: z.string(),
});

// Schéma de la réponse structurée attendue du LLM (Anubis)
export const AnubisLLMResponseSchema = z.object({
    message: z.string().describe("La question ou le message d'Anubis pour l'utilisateur"),
    choices: z.array(z.string()).min(2).max(4)
        .describe("Toujours entre 2 et 4 choix. Si une saisie spécifique est nécessaire, ajouter le type d'input (DATE_PICKER, TIME_PICKER, TEXT_INPUT, NUMBER_INPUT) comme dernier choix"),
    done: z.boolean()
        .describe("true si Anubis a assez d'informations pour créer l'item"),
    itemType: z.enum(["TASK", "EVENT"]).optional()
        .describe("Le type d'item à créer (seulement si done=true)"),
    item: z.record(z.string(), z.unknown()).optional()
        .describe("Les données de l'item à créer (seulement si done=true)"),
});

export const AgentResponseSchema = z.object({
    agent: z.string(),
    actionId: z.string().optional(),
    title: z.string().optional(),
    message: z.string(),
    choices: z.array(z.string()).min(2).max(4).optional(),
    done: z.boolean(),
    createdItem: z.record(z.string(), z.unknown()).optional(),
});
