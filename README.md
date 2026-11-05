# PEA Tracker

Suivi automatique du PEA et du wallet crypto Trade Republic : dashboard en ligne (GitHub Pages), page d'aide détaillée et mail de synthèse.

**Dashboard** : https://donsanchitoo.github.io/pea_tracker/
**Guide des indicateurs** : https://donsanchitoo.github.io/pea_tracker/aide.html

## Principe

`data/transactions.csv` est le registre de toutes les opérations (achats, ventes, dividendes, transferts). Il fait foi. À partir de lui et des cours Yahoo Finance, le moteur reconstruit l'historique jour par jour depuis l'ouverture du PEA (02/09/2025) et calcule :

- valeur, capital investi, PRU et plus-value **calculés comme Trade Republic** ;
- performance : gain total, TWR, TRI, comparaison au MSCI World et au Livret A, portefeuilles fantômes, rendements mensuels ;
- risque : volatilité, drawdown, Sharpe, Sortino, Calmar, VaR/CVaR, bêta, alpha, tracking error ;
- allocation : par ligne, classe, zone géographique (transparence des ETF), efficacité des plans en parts entières ;
- fiscalité PEA (compteur 5 ans, impôt avant/après 2030, plafond) et projection.

Un contrôle compare le registre aux écrans TR (`data/reconciliation.csv`) : quantités, PRU et performances doivent être identiques.

Tout se met à jour seul : cours, plans exécutés, dividendes (Yahoo, versés 2 jours ouvrés après détachement), staking (taux paramétrable), taux officiels (Eurostat, service-public, BCE), actualités FR/EN par ligne (Google Actualités, presse de référence en tête) et catalogue des instruments (Euronext + CoinGecko).

**Mes données** (dans le dashboard) modifie tout sans toucher au code : opérations, versements ponctuels, plans d'épargne, nouvelles lignes (recherche par nom, mnémonique ou ISIN), paramètres, relevés TR. Les changements sont enregistrés dans ce dépôt via l'API GitHub (jeton personnel stocké uniquement dans le navigateur), puis le dashboard se recalcule.

## Automatisation (GitHub Actions)

| Quand | Quoi |
| :--- | :--- |
| Chaque soir de bourse, ~18h30 | Cours de clôture, dashboard recalculé |
| Chaque matin de semaine, ~6h15 | Plans du 16 enregistrés (estimation `AUTO`), mails |
| Lundi matin | Mail de synthèse hebdomadaire (mouvements de la semaine, top 5 des actus) |
| Jour ouvré après l'exécution des plans | Mail « plans exécutés » |

Secrets requis (`Settings > Secrets and variables > Actions`) : `EMAIL_USER`, `EMAIL_PASS` (mot de passe d'application Gmail), `EMAIL_RECEIVER`.
Droits : `Settings > Actions > General > Workflow permissions > Read and write`.
Lancement manuel : `Actions > PEA Tracker > Run workflow` (choix du mail).

## Fichiers

| Fichier | Rôle |
| :--- | :--- |
| `config.json` | Actifs (ticker, ISIN, frais, zones), plans d'épargne, PEA, fiscalité, scénarios |
| `data/transactions.csv` | Registre des opérations, **à maintenir** |
| `data/reconciliation.csv` | Relevés de l'appli TR pour le contrôle |
| `data/prices.csv`, `data/corporate_actions.json` | Cache des cours et splits (généré) |
| `data/dashboard.js`, `data/history.csv` | Données du dashboard et historique journalier (générés) |
| `data/state.json` | Mémoire des mails envoyés (généré) |
| `data/live_params.json`, `data/news.json`, `data/catalog.json` | Taux officiels, actus, catalogue d'instruments (générés) |
| `index.html`, `aide.html`, `assets/` | Dashboard et guide |
| `pea_tracker.py`, `tracker/` | Moteur Python |

## Mettre à jour

Depuis le dashboard : **Mes données** (jeton GitHub à créer une fois par appareil, procédure dans l'onglet « Connexion GitHub »).
À la main : `data/transactions.csv` (une ligne par opération ; achat sans quantité = achat au montant) et `config.json` (lignes, plans, paramètres). Détail dans la section « Mes données » du guide.

## En local

```bash
pip install -r requirements.txt
python pea_tracker.py                      # cours + plans + dashboard
python pea_tracker.py --preview apercu     # + aperçu du mail dans ./apercu (sans envoi)
python -m http.server                      # puis http://localhost:8000
```
