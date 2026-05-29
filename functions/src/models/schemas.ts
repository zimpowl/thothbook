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
    stuffId: z.string().min(1),
    answer: z.string().min(1, "La réponse ne peut pas être vide"),
});

// --- Schémas de sortie des flows ---

export const CaptureStuffOutputSchema = z.object({
    stuffId: z.string(),
});

export const InputTypeSchema = z.enum([
    "text_input",
    "number_input",
    "date_picker",
    "time_picker",
    "single_choice",
    "yes_no",
]);

// Schéma de la réponse structurée attendue du LLM (Anubis)
export const AnubisLLMResponseSchema = z.object({
    message: z.string().describe("La question ou le message d'Anubis pour l'utilisateur"),
    inputType: InputTypeSchema.describe("Le type de champ à afficher côté client"),
    choices: z.array(z.string()).optional()
        .describe("Les choix possibles (seulement pour single_choice)"),
    fieldKey: z.string()
        .describe("La clé du champ concerné (ex: context, priority, startDate)"),
    done: z.boolean()
        .describe("true si Anubis a assez d'informations pour créer l'item"),
    itemType: z.enum(["TASK", "EVENT"]).optional()
        .describe("Le type d'item à créer (seulement si done=true)"),
    item: z.record(z.string(), z.unknown()).optional()
        .describe("Les données de l'item à créer (seulement si done=true)"),
});

export const AgentResponseSchema = z.object({
    agent: z.string(),
    stuffId: z.string().optional(),
    message: z.string(),
    inputType: InputTypeSchema,
    choices: z.array(z.string()).optional(),
    fieldKey: z.string(),
    done: z.boolean(),
    createdItem: z.record(z.string(), z.unknown()).optional(),
});
