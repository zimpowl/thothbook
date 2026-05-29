/**
 * ThothBook — Système d'agents IA pour organisation personnelle (GTD)
 *
 * Architecture Genkit :
 * - captureStuff : POST — Capture rapide d'une idée brute (pas d'IA)
 * - startChat : GET — Thoth cherche un stuff TODO et lance Anubis
 * - answerChat : POST — Continue la conversation avec Anubis
 *
 * Routage : Thoth orchestre les agents (V1 = simple if/else)
 */

import {onRequest} from "firebase-functions/v2/https";
import {defineSecret} from "firebase-functions/params";
import * as admin from "firebase-admin";

// Initialiser Firebase Admin
admin.initializeApp();

// Secrets Firebase
const geminiKey = defineSecret("GEMINI_API_KEY");

// Importer les flows
import {captureStuffFlow} from "./flows/captureStuff.js";
import {startChatFlow} from "./flows/startChat.js";
import {answerChatFlow} from "./flows/answerChat.js";

/**
 * POST /captureStuff
 * Body: { "text": "mon idée brute" }
 * Response: { "stuffId": "abc123" }
 */
export const captureStuff = onRequest(
    {maxInstances: 10},
    async (req, res) => {
        try {
            const result = await captureStuffFlow(req.body);
            res.json(result);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Erreur inconnue";
            res.status(400).json({error: message});
        }
    },
);

/**
 * GET /startChat
 * Pas de paramètres — Thoth trouve le prochain stuff TODO
 * Response: AgentResponse (première question d'Anubis)
 */
export const startChat = onRequest(
    {maxInstances: 10, secrets: [geminiKey]},
    async (_req, res) => {
        try {
            const result = await startChatFlow();
            res.json(result);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Erreur inconnue";
            res.status(400).json({error: message});
        }
    },
);

/**
 * POST /answerChat
 * Body: { "actionId": "abc123", "answer": "réponse de l'utilisateur" }
 * Response: AgentResponse (prochaine question ou item créé)
 */
export const answerChat = onRequest(
    {maxInstances: 10, secrets: [geminiKey]},
    async (req, res) => {
        try {
            const result = await answerChatFlow(req.body);
            res.json(result);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Erreur inconnue";
            res.status(400).json({error: message});
        }
    },
);
