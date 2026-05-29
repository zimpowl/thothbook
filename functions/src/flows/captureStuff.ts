import {ai} from "../config/genkit.js";
import {CaptureStuffInputSchema, CaptureStuffOutputSchema} from "../models/schemas.js";
import {createStuff} from "../services/firestore.js";

/**
 * Flow 1 : Capture d'un stuff (étape "Capture" de GTD).
 * Aucune intelligence ici, juste du stockage rapide.
 */
export const captureStuffFlow = ai.defineFlow(
    {
        name: "captureStuff",
        inputSchema: CaptureStuffInputSchema,
        outputSchema: CaptureStuffOutputSchema,
    },
    async (input) => {
        const stuff = await createStuff(input.text);
        return {stuffId: stuff.id};
    },
);
