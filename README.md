# ⚽ Football Hub

Un agrégateur personnel de résumés de matchs YouTube, conçu pour être hébergé gratuitement sur GitHub Pages et mis à jour automatiquement par GitHub Actions.

## Ce que fait le projet

- surveille plusieurs chaînes YouTube via leur flux Atom/RSS public ;
- récupère leurs dernières vidéos automatiquement ;
- détecte les vidéos qui ressemblent à des résumés/highlights ;
- associe les vidéos aux équipes configurées ;
- déduplique les vidéos d'un même match autant que possible ;
- affiche une interface mobile avec filtres par équipe, source et statut ;
- mémorise dans ton navigateur les équipes favorites et les vidéos déjà vues ;
- n'a besoin ni de serveur personnel ni de base de données ;
- peut fonctionner sans clé API YouTube.

> Le flux YouTube utilisé est le format Atom documenté par Google pour les notifications de chaînes : `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`.

## 1. Créer le dépôt

Crée un dépôt GitHub nommé par exemple `football-hub` et pousse **tout le contenu de ce dossier** dans la branche `main`.

## 2. Configurer les équipes et les chaînes

Copie `config.example.json` vers `config.json` puis remplace les exemples par tes vraies équipes et tes vraies chaînes.

Tu peux simplement renseigner `youtube_url` avec l'URL de la chaîne (`https://www.youtube.com/@nom` ou `/channel/UC...`). Le collecteur essaie de retrouver automatiquement le Channel ID.

Pour une fiabilité maximale, tu peux aussi renseigner directement `youtube_channel_id` (`UC...`).

## 3. Activer GitHub Pages

Dans le dépôt :

`Settings` → `Pages` → `Build and deployment` → `Source` → **GitHub Actions**.

Le workflow unique `update-and-deploy.yml` collecte les données et publie ensuite le contenu du dossier `site/` + `data/`.

## 4. Lancer la collecte

Le workflow `update-data.yml` lance la collecte périodiquement et peut aussi être lancé manuellement depuis l'onglet `Actions`.

Lorsqu'il trouve de nouvelles vidéos, il met à jour `data/videos.json`, puis le workflow de déploiement publie la nouvelle version du site.

## 5. Personnaliser dans le site

Dans l'application :

- sélectionne les équipes à afficher ;
- active `Nouveaux seulement` pour ne voir que les vidéos non lues ;
- filtre par source ;
- change le thème clair/sombre ;
- utilise `Réinitialiser` pour effacer les préférences locales.

Les préférences restent dans le navigateur via `localStorage`. Le dépôt ne stocke pas ton historique personnel.

## Limites connues

Les flux YouTube ne fournissent qu'un nombre limité d'entrées récentes et peuvent rencontrer des erreurs temporaires. Le collecteur gère les erreurs source par source et conserve les données précédemment récupérées.

Le classement d'une vidéo comme « résumé » est heuristique : titre + mots-clés + présence d'une équipe configurée. Les titres atypiques peuvent donc nécessiter l'ajout d'alias ou de mots-clés dans `config.json`.

## Structure

```text
football-hub/
├── .github/workflows/
│   ├── deploy.yml
│   └── update-data.yml
├── collector/
│   └── collect.py
├── data/
│   └── videos.json
├── site/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tests/
│   └── test_collector.py
├── config.example.json
└── README.md
```

## Installation ultra-rapide

1. Copie tout le dossier dans un dépôt GitHub.
2. Modifie uniquement `config.json` avec tes équipes et tes chaînes.
3. Active `Settings → Pages → Source → GitHub Actions`.
4. Dans `Actions`, lance `Update and deploy Football Hub` une première fois avec `Run workflow`.
5. Ouvre l'URL Pages indiquée par GitHub.

Le projet est volontairement sans clé API dans sa version de base : il s'appuie sur les flux Atom publics des chaînes. Google documente encore en 2026 ce format de flux pour les chaînes YouTube et les notifications associées. Des erreurs temporaires de flux sont toutefois possibles. 
