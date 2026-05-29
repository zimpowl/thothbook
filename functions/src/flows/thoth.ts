/**
 * Thoth — Le routeur principal.
 *
 * Thoth est le serviteur du pharaon (le client). Il orchestre les agents :
 *   - ANUBIS : qualifie les stuffs (stuff → task/event/list) + review des stuffs WAIT
 *   - HORUS : guide l'exécution des tâches qualifiées
 *
 * Routing par priorité :
 *   1. Stuff TODO → Anubis (qualification initiale)
 *   2. Stuff WAIT + toutes tâches DONE → Anubis (mode review)
 *   3. Tâche TODO → Horus (exécution)
 */
export type AgentName = "ANUBIS" | "HORUS" | "KHONSOU" | "MAAT";

export type RouteResult = {
    agent: AgentName;
    mode?: "qualification" | "review";
    stuffId?: string;
};

/**
 * Détermine quel agent doit être lancé par priorité.
 */
export function resolveRoute(options: {
    hasTodoStuff: boolean;
    waitingReviewStuffId?: string;
    hasTodoTask: boolean;
}): RouteResult {
    // 1. Stuff TODO → Anubis qualification
    if (options.hasTodoStuff) {
        return {agent: "ANUBIS", mode: "qualification"};
    }

    // 2. Stuff WAIT avec toutes tâches done → Anubis review
    if (options.waitingReviewStuffId) {
        return {agent: "ANUBIS", mode: "review", stuffId: options.waitingReviewStuffId};
    }

    // 3. Tâche TODO → Horus
    if (options.hasTodoTask) {
        return {agent: "HORUS"};
    }

    // Rien à faire
    return {agent: "HORUS"};
}
