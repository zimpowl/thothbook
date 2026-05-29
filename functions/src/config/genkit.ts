import {genkit} from "genkit";
import { googleAI } from '@genkit-ai/google-genai'

/**
 * Configuration centralisée de Genkit.
 *
 * Pour switcher de modèle :
 * 1. Installer le plugin (ex: genkitx-openai pour GPT)
 * 2. Ajouter le plugin dans la liste ci-dessous
 * 3. Changer DEFAULT_MODEL
 */
export const ai = genkit({
    plugins: [
        googleAI({apiKey: process.env.GOOGLE_GENAI_API_KEY}),
    ],
});

/**
 * Modèle par défaut utilisé par tous les agents.
 * Changer cette ligne pour switcher de provider.
 */
export const DEFAULT_MODEL = 'googleai/gemini-3.1-flash-lite';
