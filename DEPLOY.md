# Déploiement de « Thothbook »

Architecture : **frontend statique** (`web/index.html`) sur **Firebase Hosting**,
**backend FastAPI** (Python) sur **Google Cloud Run**. Firebase Hosting redirige
`/api/**` vers Cloud Run (voir `firebase.json`), donc tout est sur le même domaine
(pas de souci CORS).

> ⚠️ **Sécurité — à faire en premier.** Le fichier `.env` est actuellement suivi par git
> (il contient tes secrets). Retire-le du suivi et change tes clés par précaution :
> ```bash
> git rm --cached .env
> git commit -m "Retire .env du suivi (secrets)"
> ```
> Le nouveau `.gitignore` empêchera de le re-commiter. Régénère NEO4J_PASSWORD et tes
> clés LLM dans leurs consoles respectives s'ils ont été poussés sur un remote.

---

## 0. Prérequis (une fois)

- Un projet **Firebase** (= projet Google Cloud). Note son **Project ID**.
- Installer les CLIs : `npm i -g firebase-tools` et le **gcloud SDK**.
- `firebase login` et `gcloud auth login`, puis `gcloud config set project TON_PROJECT_ID`.
- Remplace `TON_PROJECT_ID` dans `.firebaserc`.

## 1. Activer l'authentification Firebase

Console Firebase → **Authentication** → *Get started* → onglet **Sign-in method** :
active **Adresse e-mail/Mot de passe** et **Google**.

## 2. Récupérer la config web (frontend)

Console Firebase → **Paramètres du projet** (roue crantée) → section *Tes applications* →
ajoute une **application Web** → copie l'objet `firebaseConfig`.
Colle ces valeurs dans `web/index.html` (bloc `const firebaseConfig = {…}`, en haut du script,
balisé `⚠️ REMPLACE ces valeurs`). Ces clés sont **publiques** par nature (pas un secret).

## 3. Mettre à jour les API keys (Secret Manager)

Commence par fixer l'ID du projet une fois pour toute la session :

```bash
PROJECT_ID="thothbook-app"
```

> Si `gcloud` n'est pas dans le PATH, remplace `gcloud` par `./google-cloud-sdk/bin/gcloud`
> dans les commandes ci-dessous (depuis la racine du repo).

Créer les secrets (commande idempotente avec `|| true`) :

```bash
gcloud secrets create NEO4J_PASSWORD --replication-policy="automatic" --project "$PROJECT_ID" || true
gcloud secrets create GOOGLE_API_KEY --replication-policy="automatic" --project "$PROJECT_ID" || true
gcloud secrets create STRIPE_SECRET_KEY --replication-policy="automatic" --project "$PROJECT_ID" || true
gcloud secrets create STRIPE_WEBHOOK_SECRET --replication-policy="automatic" --project "$PROJECT_ID" || true
```

Ajouter une nouvelle version (rotation) :

```bash
printf "%s" "NOUVEAU_NEO4J_PASSWORD" | gcloud secrets versions add NEO4J_PASSWORD --data-file=- --project "$PROJECT_ID"
printf "%s" "NOUVELLE_GOOGLE_API_KEY" | gcloud secrets versions add GOOGLE_API_KEY --data-file=- --project "$PROJECT_ID"
printf "%s" "NOUVELLE_STRIPE_SECRET_KEY" | gcloud secrets versions add STRIPE_SECRET_KEY --data-file=- --project "$PROJECT_ID"
printf "%s" "NOUVEAU_STRIPE_WEBHOOK_SECRET" | gcloud secrets versions add STRIPE_WEBHOOK_SECRET --data-file=- --project "$PROJECT_ID"
```

Donner au service runtime Cloud Run le droit de lire les secrets :

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

## 4. Déployer le backend sur Cloud Run

Le backend a besoin de ces variables : `APP_BASE_URL` + secrets (`NEO4J_PASSWORD`,
`GOOGLE_API_KEY` pour Gemini ou `OPENAI_API_KEY`, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`).
**Ne définis PAS `FIREBASE_CREDENTIALS`** : sur Cloud Run, l'authentification Admin
Firebase utilise automatiquement les *Application Default Credentials* du projet.

```bash
# Depuis la racine du repo.
cd "/Users/pziwiakowsky/IdeaProjects/thothbook"
GCLOUD="./google-cloud-sdk/bin/gcloud"
PROJECT_ID="thothbook-app"

# Backend Cloud Run
"$GCLOUD" run deploy thothbook \
  --project "$PROJECT_ID" \
  --region europe-west1 \
  --source . \
  --allow-unauthenticated \
  --set-secrets "NEO4J_PASSWORD=NEO4J_PASSWORD:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,STRIPE_SECRET_KEY=STRIPE_SECRET_KEY:latest,STRIPE_WEBHOOK_SECRET=STRIPE_WEBHOOK_SECRET:latest" \
  --set-env-vars "APP_BASE_URL=https://thothbook-app.web.app"

# Frontend Firebase Hosting
firebase deploy --only hosting --project "$PROJECT_ID"
```

Notes :
- `--source .` fait construire l'image à partir du `Dockerfile` (via Cloud Build).
- `--allow-unauthenticated` : l'accès réseau est public, mais **chaque appel API exige un
  jeton Firebase valide** (vérifié dans `auth.py`). C'est l'app qui protège, pas le réseau.
- `--min-instances 1` : évite les démarrages à froid **et** garde la mémoire de conversation
  (`_historiques`) stable (sinon elle est par-instance — voir « Limites » du plan).
- En provider OpenAI, remplace `GOOGLE_API_KEY` par `OPENAI_API_KEY` partout (secret + `--set-secrets`).

## 3 bis. Configurer Stripe

- Dans Stripe, crée les produits côté code uniquement : les **packs** viennent de `config.yaml`.
- Ajoute un webhook Stripe pointant vers `https://TON_DOMAINE/api/paiements/webhook`.
- Événements minimum à écouter :
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
- Le backend crédite l'utilisateur **uniquement** depuis ce webhook, de manière idempotente
  via la référence unique de session Stripe.

Vérifie que le `serviceId` et la `region` dans `firebase.json` correspondent bien au service déployé.

## 5. Déployer le frontend sur Firebase Hosting

```bash
firebase use "$PROJECT_ID"
firebase deploy --only hosting --project "$PROJECT_ID"
```

Ouvre l'URL Hosting affichée (`https://thothbook.web.app/`). L'écran de connexion
apparaît ; connecte-toi ; l'app charge ton état via `/api/...` (servi par Cloud Run).

## 6. Vérifier

- Onglet réseau du navigateur : les appels `/api/etat`, `/api/suggestions`… renvoient 200.
- Un appel sans être connecté → 401. Crédits épuisés → 402 avec message de recharge.
- Nouvel utilisateur : solde initial = **0 crédit** (configurable dans `config.yaml`).

---

## Développement local

```bash
pip install -r requirements.txt && pip install -e .
cp .env.example .env   # renseigne NEO4J_PASSWORD, la clé LLM, FIREBASE_CREDENTIALS et les secrets Stripe si tu testes le paiement
uvicorn thothbook.api:app --reload
```

- `FIREBASE_CREDENTIALS` (local) = chemin vers le JSON de **compte de service** Firebase
  (Console → Paramètres → *Comptes de service* → *Générer une nouvelle clé privée*).
  **Ne commite jamais ce fichier** (déjà couvert par `.gitignore`).
- En local, le backend sert aussi `web/index.html` sur `/` (pratique pour tester).
- La **CLI** (`python -m thothbook`) reste mono-utilisateur de dev (`uid="cli-dev"`), sans
  Firebase ni crédits — utile pour tester rapidement le graphe.

## Réglage des prix / marge

`config.yaml` → section `tarifs` : renseigne les **vrais** prix par million de tokens de ton
modèle (input/output) et la `marge` (multiplicateur). Les crédits débités = coût réel × marge × `credits.par_euro`, arrondi au-dessus.
Le solde initial, le minimum par appel et les packs de recharge sont dans `credits.*`.
