import {ai, DEFAULT_MODEL} from "../config/genkit.js";
import {CaptureStuffInputSchema, CaptureStuffOutputSchema} from "../models/schemas.js";
import {createStuff} from "../services/firestore.js";

/**
 * Réécrit un texte brut capturé en une formulation propre et lisible.
 */
async function rewriteStuffText(rawText: string): Promise<string> {
    const result = await ai.generate({
        model: DEFAULT_MODEL,
        prompt: `Réécris ce texte brut en une formulation propre, concise et lisible en français. Corrige l'orthographe, la grammaire et la casse. Ne change pas le sens. Retourne UNIQUEMENT le texte réécrit, sans guillemets ni explication.

Texte brut : "${rawText}"`,
    });
    const rewritten = result.text?.trim();
    return rewritten || rawText;
}

/**
 * Flow 1 : Capture d'un stuff (étape "Capture" de GTD).
 * Le texte brut est réécrit proprement par le LLM avant stockage.
 */
export const captureStuffFlow = ai.defineFlow(
    {
        name: "captureStuff",
        inputSchema: CaptureStuffInputSchema,
        outputSchema: CaptureStuffOutputSchema,
    },
    async (input) => {
        const cleanText = await rewriteStuffText(input.text);
        const stuff = await createStuff(cleanText);
        return {stuffId: stuff.id};
    },
);
