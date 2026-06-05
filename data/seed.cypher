// Graphe d'exemple pour « Thothbook ».
// Charge-le avec :  python -m thothbook --seed
// (ou copie-colle dans Neo4j Browser, http://localhost:7474)

MERGE (m:Moi {id:'moi'});

// --- Objectifs ---
MERGE (o1:Objectif {nom:'Écrire mon roman'}) SET o1.priorite='haute', o1.statut='actif';
MERGE (o2:Objectif {nom:'Me remettre au sport'}) SET o2.priorite='moyenne', o2.statut='actif';
MERGE (o3:Objectif {nom:'Garder le lien avec mes amis'}) SET o3.priorite='moyenne', o3.statut='actif';

// --- Relations Moi -> Objectifs ---
MATCH (m:Moi {id:'moi'}), (o:Objectif) MERGE (m)-[:VISE]->(o);

// --- Tâches ---
MERGE (t1:Tache {nom:'Écrire le chapitre 3'}) SET t1.urgence='haute', t1.statut='a_faire', t1.duree_min=60;
MERGE (t2:Tache {nom:'Aller courir 30 min'}) SET t2.urgence='moyenne', t2.statut='a_faire', t2.duree_min=30;
MATCH (m:Moi {id:'moi'}), (t:Tache) MERGE (m)-[:DOIT_FAIRE]->(t);
MATCH (t:Tache {nom:'Écrire le chapitre 3'}), (o:Objectif {nom:'Écrire mon roman'}) MERGE (t)-[:SERT]->(o);
MATCH (t:Tache {nom:'Aller courir 30 min'}), (o:Objectif {nom:'Me remettre au sport'}) MERGE (t)-[:SERT]->(o);

// --- Habitude ---
MERGE (h:Habitude {nom:'Lire 20 min le soir'}) SET h.frequence='quotidienne';
MATCH (m:Moi {id:'moi'}), (h:Habitude) MERGE (m)-[:PRATIQUE]->(h);

// --- Personnes ---
MERGE (p1:Personne {nom:'Paul'});
MERGE (p2:Personne {nom:'Léa'});
MATCH (m:Moi {id:'moi'}), (p:Personne) MERGE (m)-[:CONNAIT]->(p);

// --- État actuel ---
MATCH (m:Moi {id:'moi'}) CREATE (e:Etat {energie:'moyenne', humeur:'concentré', date:date()}) MERGE (m)-[:RESSENT]->(e);
