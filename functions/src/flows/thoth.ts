/**
 * Thoth — Le routeur principal.
 *
 * Thoth est le serviteur du pharaon (le client). Il ne communique jamais
 * directement avec le LLM pour l'instant, mais il orchestre les agents.
 *
 * V1 : Routage simple basé sur le status du stuff
 *   - stuff.status === "TODO" → Anubis (clarification)
 *
 * V2 (futur) : Thoth devient un flow IA qui décide quel agent appeler
 *   - Ptah pour l'organisation et la suggestion
 *   - Maât pour la révision
 *   - etc.
 */

export type AgentName = "ANUBIS" | "PTAH" | "MAAT" | "HORUS";

/**
 * Détermine quel agent doit traiter un stuff selon son état.
 * Pour l'instant, c'est toujours Anubis.
 */
export function routeStuff(_stuffStatus: string): AgentName {
    // V1 : Toujours Anubis pour la clarification
    return "ANUBIS";
}
