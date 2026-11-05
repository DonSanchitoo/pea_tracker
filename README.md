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

## Automatisation (GitHub Actions)

| Quand | Quoi |
| :--- | :--- |
| Chaque soir de bourse, ~18h30 | Cours de clôture, dashboard recalculé |
| Chaque matin de semaine, ~6h15 | Plans du 16 enregistrés (estimation `AUTO`), mails |
| Lundi matin | Mail de synthèse hebdomadaire |
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
| `index.html`, `aide.html`, `assets/` | Dashboard et guide |
| `pea_tracker.py`, `tracker/` | Moteur Python |

## Mettre à jour

- **Plan du mois** : le robot l'enregistre avec un montant estimé (`source = AUTO`). Pour être au centime, remplace le montant par celui affiché dans TR et passe la source à `TR`.
- **Achat ponctuel, vente, dividende** : ajoute une ligne dans `data/transactions.csv`.
- **Changer un plan** : rubrique `plans` de `config.json`.

Le détail (format des lignes, TTF, nouvel actif) est dans la section « Mettre à jour mes données » du guide.

## En local

```bash
pip install -r requirements.txt
python pea_tracker.py                      # cours + plans + dashboard
python pea_tracker.py --preview apercu     # + aperçu du mail dans ./apercu (sans envoi)
python -m http.server                      # puis http://localhost:8000
```
