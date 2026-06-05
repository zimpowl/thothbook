# Thothbook

Assistant d'organisation personnelle. Thothbook connaît ta vie (objectifs, tâches,
habitudes, amis, état) stockée dans un **graphe Neo4j**, et te **suggère quoi faire
et quand**. Tu **valides** ses suggestions (elles s'écrivent dans le graphe) ou tu
**clarifies** (il re-suggère).

```
Tu écris  →  Thothbook lit ton graphe  →  propose des suggestions
                                              ↓
                        « ok » → écrit dans le graphe   |   clarification → re-suggère
```

## 1. Prérequis : une base Neo4j

Deux options — le code est identique, seule l'URI change dans `config.yaml`.

### Option A — Cloud (Neo4j Aura) : zéro installation

1. Crée une instance gratuite : https://neo4j.com/cloud/aura/ (AuraDB Free).
2. **Télécharge le fichier de credentials** à la création (l'URI + le mot de passe ne s'affichent qu'une fois).
3. Dans `config.yaml`, mets l'URI fournie : `uri: neo4j+s://xxxxx.databases.neo4j.io`.
4. Visualise le graphe directement dans la console Aura (intégrée au navigateur).

Avantages : rien à installer, accessible partout, géré.
Inconvénient : tes données (intimes) sont dans le cloud, et le tier gratuit est limité.

### Option B — Local (Neo4j Desktop) : tout reste chez toi

1. Télécharge et installe Neo4j Desktop : https://neo4j.com/download/
2. Crée une base locale (« New » → « Local DBMS »), choisis un **mot de passe** (retiens-le).
3. Clique **Start**. La base écoute sur `bolt://localhost:7687`.
4. Ouvre **Neo4j Browser** (bouton « Open ») → c'est l'écran où tu **verras le graphe**.

> Alternative Docker (1 commande) :
> ```bash
> docker run -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/ton_password neo4j:5
> ```

Recommandation : **Aura pour démarrer vite**, **local si la confidentialité de tes données prime**.

## 2. Installer le projet

```bash
cd "thothbook"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # installe les dépendances + le package
```

## 3. Configurer

```bash
cp .env.example .env
```
Édite `.env` : mets ton `NEO4J_PASSWORD` et la clé du LLM choisi
(`GOOGLE_API_KEY` pour Gemini, `OPENAI_API_KEY` pour OpenAI).

Le choix du LLM se fait dans **`config.yaml`** :
```yaml
llm:
  provider: google_genai      # ou "openai"
  model: gemini-2.0-flash     # ou "gpt-4o-mini"
```

## 4. (Optionnel) Charger un exemple de vie

```bash
python -m thothbook --seed
```
Charge quelques objectifs/tâches/amis pour avoir de quoi tester tout de suite.

## 5. L'app web (recommandé — sans prompter) 🪄

```bash
python -m thothbook --web
```
Puis ouvre **http://localhost:8000** dans ton navigateur.

À l'ouverture, Thothbook lit ton graphe et **propose tout seul** des actions, sous forme
de cartes. Sur chaque carte :
- **✅ Valider** → écrit l'action dans le graphe (Aura)
- **✏️ Ajuster** → tu précises en une phrase, il re-propose
- **✕ Plus tard** → la carte disparaît

Le bouton **« ✨ Que dois-je faire maintenant ? »** régénère des suggestions.
Tu ne tapes que pour clarifier — le reste se fait au clic.

### Crédits & recharge

- Le solde est désormais affiché en **crédits entiers** (ex. `🪙 Crédits : 1900`).
- Les appels IA débitent des crédits selon la **consommation réelle** du modèle, une
  **forte marge** et un **minimum par appel** (voir `config.yaml`).
- Trois **packs Stripe** sont proposés dans une popup : le deuxième inclut un bonus,
  le troisième un bonus encore plus généreux.
- Quand le solde tombe à **0**, la popup de recharge s'ouvre automatiquement ; le bouton
  **＋** doré en haut à droite permet aussi de recharger à tout moment.

**Sur chaque tâche « À faire »** :
- **▶️ Focus** → ouvre un minuteur de concentration (25 min, pause / +5 min). Quand tu cliques **✓ Terminé**, la tâche est marquée faite.
- **✓** → marque la tâche faite tout de suite, sans minuteur.

**Onglet « 📅 Agenda »** : un calendrier plein écran (façon Google Agenda) qui affiche
tout ce qui est planifié — créneaux de tâches (bleu) et sorties (orange). Vues **Mois**
et **Semaine**, flèches ← → pour changer de période, bouton **Aujourd'hui**. Les
événements sur plusieurs jours s'étendent sur les cases (une seule étiquette par ligne,
dupliquée d'une semaine à l'autre). Au survol d'un événement, deux pictos : **✏️ modifier**
(ouvre un formulaire titre / début / fin — déplace l'événement existant, sans doublon) et
**🗑️ supprimer**.

## 5 bis. Discuter en terminal (mode dev)

```bash
python -m thothbook
```

Exemples de ce que tu peux écrire :
- « Je veux écrire un roman cette année et reprendre le sport. »
- « Qu'est-ce que je devrais faire ce week-end ? »
- « Est-ce une bonne idée de voir Paul vendredi soir ? »
- « Je suis crevé cette semaine. »

Thothbook répond avec des suggestions numérotées. Tu réponds :
- **`ok`** → il écrit toutes les suggestions dans le graphe
- **`1,3`** → il n'écrit que les suggestions 1 et 3
- **une phrase** → c'est une clarification, il re-suggère
- **`voir`** → affiche le contenu actuel du graphe · **`q`** → quitter

## 6. Voir la base se remplir 👀

Après chaque validation, ouvre **Neo4j Browser** (http://localhost:7474) et lance :
```cypher
MATCH (n) RETURN n
```
Tu verras apparaître tes nœuds (`Objectif`, `Tache`, `Sortie`, `Personne`…) et leurs
relations. Relance la requête après chaque `ok` : le graphe grossit en direct.

Quelques requêtes utiles :
```cypher
// Ce qui sert un objectif donné
MATCH (x)-[:SERT]->(o:Objectif {nom:'Écrire mon roman'}) RETURN x, o;

// Ton planning
MATCH (x)-[:PLANIFIE_A]->(c:Creneau) RETURN x.nom, c.debut, c.fin ORDER BY c.debut;
```

> **Dans IntelliJ** : si tu as IntelliJ IDEA **Ultimate**, l'outil *Database*
> (View → Tool Windows → Database) peut se connecter à Neo4j et explorer les données.
> En **Community**, utilise Neo4j Browser (déjà installé avec Neo4j Desktop).

## Structure du projet

```
src/thothbook/
  config.py    # charge config.yaml + .env
  schemas.py   # structure des suggestions/actions (Pydantic)
  graphe.py    # Neo4j : lecture du contexte + écriture des actions
  llm.py       # modèle LLM paramétrable (OpenAI / Gemini)
  conseil.py   # contexte + message → suggestions
  cli.py       # boucle conversationnelle (terminal)
  __main__.py  # python -m thothbook [--seed]
data/seed.cypher
config.yaml · .env (à créer)
```
