# Déploiement de « Le Cadre »

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

## 3. Déployer le backend sur Cloud Run

Le backend a besoin de ces variables d'environnement (secrets) sur Cloud Run :
`NEO4J_PASSWORD`, la clé LLM (`GOOGLE_API_KEY` pour Gemini, ou `OPENAI_API_KEY`),
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, et `APP_BASE_URL` (URL publique du front, ex `https://thothbook.web.app`).
**Ne définis PAS `FIREBASE_CREDENTIALS`** : sur Cloud Run, l'authentification Admin
Firebase utilise automatiquement les *Application Default Credentials* du projet.

```bash
# Depuis la racine du repo. Le nom du service DOIT correspondre au serviceId de firebase.json
# (« le-cadre ») et la région à celle de firebase.json (« europe-west1 »).
gcloud run deploy le-cadre \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --min-instances 1 \
  --set-env-vars "NEO4J_PASSWORD=xxx,GOOGLE_API_KEY=yyy,APP_BASE_URL=https://thothbook.web.app,STRIPE_SECRET_KEY=sk_xxx,STRIPE_WEBHOOK_SECRET=whsec_xxx"
```

Notes :
- `--source .` fait construire l'image à partir du `Dockerfile` (via Cloud Build).
- `--allow-unauthenticated` : l'accès réseau est public, mais **chaque appel API exige un
  jeton Firebase valide** (vérifié dans `auth.py`). C'est l'app qui protège, pas le réseau.
- `--min-instances 1` : évite les démarrages à froid **et** garde la mémoire de conversation
  (`_historiques`) stable (sinon elle est par-instance — voir « Limites » du plan).
- Pour des secrets propres, préfère **Secret Manager** :
  `--set-secrets "NEO4J_PASSWORD=neo4j-pwd:latest,GOOGLE_API_KEY=gemini-key:latest,STRIPE_SECRET_KEY=stripe-secret:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook:latest"` puis
  `--update-env-vars "APP_BASE_URL=https://thothbook.web.app"`.

## 3 bis. Configurer Stripe

- Dans Stripe, crée les produits côté code uniquement : les **packs** viennent de `config.yaml`.
- Ajoute un webhook Stripe pointant vers `https://TON_DOMAINE/api/paiements/webhook`.
- Événements minimum à écouter :
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
- Le backend crédite l'utilisateur **uniquement** depuis ce webhook, de manière idempotente
  via la référence unique de session Stripe.

Vérifie que le `serviceId` et la `region` dans `firebase.json` correspondent bien au service déployé.

## 4. Déployer le frontend sur Firebase Hosting

```bash
firebase deploy --only hosting
```

Ouvre l'URL Hosting affichée (`https://thothbook.web.app/`). L'écran de connexion
apparaît ; connecte-toi ; l'app charge ton état via `/api/...` (servi par Cloud Run).

## 5. Vérifier

- Onglet réseau du navigateur : les appels `/api/etat`, `/api/suggestions`… renvoient 200.
- Un appel sans être connecté → 401. Crédits épuisés → 402 avec message de recharge.
- Nouvel utilisateur : solde initial = **0 crédit** (configurable dans `config.yaml`).

---

## Développement local

```bash
pip install -r requirements.txt && pip install -e .
cp .env.example .env   # renseigne NEO4J_PASSWORD, la clé LLM, FIREBASE_CREDENTIALS et les secrets Stripe si tu testes le paiement
uvicorn le_cadre.api:app --reload
```

- `FIREBASE_CREDENTIALS` (local) = chemin vers le JSON de **compte de service** Firebase
  (Console → Paramètres → *Comptes de service* → *Générer une nouvelle clé privée*).
  **Ne commite jamais ce fichier** (déjà couvert par `.gitignore`).
- En local, le backend sert aussi `web/index.html` sur `/` (pratique pour tester).
- La **CLI** (`python -m le_cadre`) reste mono-utilisateur de dev (`uid="cli-dev"`), sans
  Firebase ni crédits — utile pour tester rapidement le graphe.

## Réglage des prix / marge

`config.yaml` → section `tarifs` : renseigne les **vrais** prix par million de tokens de ton
modèle (input/output) et la `marge` (multiplicateur). Les crédits débités = coût réel × marge × `credits.par_euro`, arrondi au-dessus.
Le solde initial, le minimum par appel et les packs de recharge sont dans `credits.*`.
