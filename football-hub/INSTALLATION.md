# Installation en 5 minutes

## 1. GitHub

Crée un dépôt public `football-hub`, puis glisse-dépose tout le contenu du dossier du projet.

## 2. Configuration

Ouvre `config.json` et ajoute tes équipes et tes chaînes.

Exemple :

```json
{
  "app": {
    "name": "Football Hub",
    "description": "Mon agrégateur personnel de résumés de matchs",
    "max_videos_per_source": 15,
    "keep_days": 45,
    "summary_keywords": [
      "highlights", "match highlights", "extended highlights", "résumé", "resumen", "all goals"
    ],
    "exclude_keywords": [
      "reaction", "preview", "prediction", "interview", "training", "transfer", "news", "analysis"
    ]
  },
  "teams": [
    {
      "id": "arsenal",
      "name": "Arsenal",
      "aliases": ["Arsenal FC"]
    }
  ],
  "sources": [
    {
      "id": "premier-league-highlights",
      "name": "Ma chaîne",
      "youtube_url": "https://www.youtube.com/@ma_chaine",
      "youtube_channel_id": "",
      "enabled": true
    }
  ]
}
```

### Conseils pour les équipes

Ajoute les variantes de nom réellement utilisées dans les titres YouTube :

```json
{
  "id": "psg",
  "name": "Paris Saint-Germain",
  "aliases": ["PSG", "Paris SG", "Paris Saint Germain"]
}
```

### Conseils pour les chaînes

Tu peux mettre une URL `@handle` dans `youtube_url`. Le collecteur tente de retrouver automatiquement le Channel ID. Pour une fiabilité maximale, remplis aussi `youtube_channel_id` avec l'identifiant `UC...` de la chaîne.

## 3. GitHub Pages

Dans le dépôt : `Settings` → `Pages` → `Build and deployment` → `Source` → **GitHub Actions**.

## 4. Premier lancement

Va dans `Actions` → `Update and deploy Football Hub` → `Run workflow`.

Le workflow collecte immédiatement les chaînes, met à jour `data/videos.json`, puis déploie le site.

## 5. Ton URL

Pour un dépôt `football-hub` appartenant à `MON_PSEUDO`, l'URL sera typiquement :

`https://MON_PSEUDO.github.io/football-hub/`

## Ce qui est déjà automatique

Le workflow planifie une collecte toutes les 30 minutes. Il est également lançable manuellement.

Les données publiques sont commitées dans `data/videos.json`, tandis que tes préférences personnelles (équipes sélectionnées, vidéos vues, thème) restent dans le navigateur.

## Important

Une chaîne très prolifique peut publier plus d'éléments que le nombre disponible dans son flux récent entre deux collectes. Le réglage `max_videos_per_source` peut être augmenté, dans les limites pratiques du flux.

YouTube peut également renvoyer temporairement une erreur sur un flux. Le collecteur conserve alors les données précédentes pour les vidéos déjà enregistrées.
