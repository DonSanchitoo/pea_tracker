# PEA Tracker : Système Automatisé de Suivi de Portefeuille

Ce projet implémente un pipeline ETL (Extract, Transform, Load) automatisé pour le suivi hebdomadaire d'un Plan d'Épargne en Actions (PEA). Il calcule les performances latentes, gère les investissements programmés (DCA) et génère des rapports visuels institutionnels.

## Architecture du système

L'outil repose sur les composants suivants :
* **Moteur d'extraction** : Script Python utilisant la bibliothèque `yfinance` pour l'accès aux données de marché en temps réel.
* **Orchestration** : GitHub Actions configuré pour une exécution récurrente (Workflow hebdomadaire).
* **Stockage de données** : Fichiers CSV structurés servant de registre transactionnel et historique.
* **Reporting** : Expédition de rapports via protocole SMTP (HTML/CSS) avec intégration de graphiques analytiques.

---

## Documentation des fichiers de données (CSV)

### 1. portfolio_state.csv
Ce fichier consigne l'état actuel des positions et sert de base au calcul des achats périodiques (DCA).

| Colonne | Unité | Description |
| :--- | :--- | :--- |
| **Ticker** | - | Identifiant Yahoo Finance de l'actif (ex: ESE.PA). |
| **Quantity** | Nombre | Quantité totale de parts détenues en portefeuille. |
| **Total_Invested** | EUR | Capital total investi sur la ligne (somme des achats). |
| **Last_Purchase_Month** | Index | Mois de la dernière exécution de l'achat automatique. |

### 2. pea_history.csv
Ce fichier constitue la base de données historique du portefeuille pour l'analyse temporelle.

* **Données de marché** : Cours de clôture pour chaque ticker configuré.
* **Total_Invested (EUR)** : Somme cumulée des capitaux versés sur le compte.
* **Total_Value (EUR)** : Valeur liquidative totale du portefeuille à la date du relevé.
* **Total_Return_Pct (%)** : Rendement global du portefeuille calculé selon la formule :

$$\text{Performance} = \left( \frac{\text{Valeur Totale} - \text{Total Investi}}{\text{Total Investi}} \right) \times 100$$

---

## Structure du rapport hebdomadaire

Le rapport transmis par email est structuré pour une lecture rapide des indicateurs de performance clés :

### Analyse de la volatilité court terme
Ce tableau présente la performance des actifs sur une période de 5 jours de bourse. Il permet d'isoler la dynamique récente du marché de la performance intrinsèque du portefeuille.

### Performance globale et plus-value latente
Cette section détaille la situation patrimoniale réelle :
* **Total investi (EUR)** : Le montant total décaissé par actif.
* **Plus-value latente (EUR)** : Le gain ou la perte nominale.
* **Performance (%)** : Le rendement pondéré par les entrées de capital.

### Graphique de performance
Le graphique (format PNG) retrace l'historique de la rentabilité globale (`Total_Return_Pct`). Il permet de visualiser l'impact de la stratégie de Dollar Cost Averaging (DCA) sur la performance à long terme.

---

## Configuration et Déploiement

### Paramétrage des Secrets GitHub
Pour le fonctionnement du service SMTP, les variables suivantes doivent être définies dans `Settings > Secrets and variables > Actions` :
* `EMAIL_USER` : Identifiant de connexion au serveur mail.
* `EMAIL_PASS` : Mot de passe d'application sécurisé.
* `EMAIL_RECEIVER` : Adresse de destination du rapport.

### Droits d'écriture
Le workflow nécessite l'activation des droits d'écriture pour mettre à jour les registres CSV après chaque exécution. Configuration requise : `Settings > Actions > General > Workflow permissions > Read and write permissions`.



# Guide de Maintenance : Automatisation vs Manuel

Il est essentiel de comprendre que le script est "intelligent" pour les calculs, mais qu'il respecte strictement la structure des fichiers que tu lui donnes. Voici comment différencier ce que le robot fait seul et ce que tu dois préparer.

---

## 1. Ce qui est 100% Automatisé (Ordi éteint)

Une fois que tes tickers sont configurés dans le code et présents dans les fichiers, GitHub Actions gère seul :

* **L'archivage hebdomadaire** : Chaque lundi, le script crée une nouvelle ligne à la fin de `pea_history.csv`.
* **L'exécution du DCA** : Le 16 du mois, le script calcule le nombre de parts achetées avec tes 450€ (250+140+60) et met à jour les colonnes `Quantity` et `Total_Invested` dans `portfolio_state.csv`.
* **La mise à jour graphique** : Le fichier `chart.png` est écrasé et remplacé par la nouvelle version incluant la semaine écoulée.

---

## 2. Ce qui est Manuel (Intervention requise)

Le script ne peut pas modifier la structure (les colonnes) de tes fichiers. Si tu décides d'ajouter un **nouvel actif** (ex: un ETF Nasdaq), tu dois effectuer ces trois étapes manuellement :

### Étape A : Mise à jour de `pea_history.csv`
Le fichier CSV est une grille fixe. Le script ne créera pas de nouvelle colonne tout seul.
* **Action** : Tu dois ouvrir le fichier et ajouter `,NOM_DU_TICKER.PA` à la fin de la première ligne (l'en-tête).

### Étape B : Mise à jour de `portfolio_state.csv`
Le script boucle sur ce fichier pour connaître tes positions. S'il n'y a pas de ligne pour le nouvel actif, il l'ignorera.
* **Action** : Ajoute une ligne à la fin : `NOM_DU_TICKER.PA,0.0,0.0,0`.

### Étape C : Mise à jour de `pea_tracker.py`
* **Action** : Ajoute le ticker et le montant du DCA mensuel dans le dictionnaire `MONTHLY_INVESTMENTS`.
```python
MONTHLY_INVESTMENTS = {
    "ESE.PA": 250,
    "NOUVEL_ACTIF.PA": 100,  # Ajouter la ligne ici (0 si pas de DCA)
    ...
}
```
---

## 3. Synthèse des opérations

| Action | Type | Fichier concerné |
| :--- | :--- | :--- |
| Enregistrer le prix de la semaine | **Automatique** | `pea_history.csv` |
| Calculer l'achat du 16 du mois | **Automatique** | `portfolio_state.csv` |
| Ajouter une colonne (Nouveau Ticker) | **Manuel** | `pea_history.csv` |
| Initialiser un nouvel actif | **Manuel** | `portfolio_state.csv` |
| Modifier le montant d'un virement | **Manuel** | `pea_tracker.py` |

---

## 4. Formule de calcul utilisée

Pour ton information, la performance affichée dans le mail et le graphique est calculée ainsi :

$$\text{Performance} = \left( \frac{\text{Valeur Totale du Portefeuille} - \text{Total Investi}}{\text{Total Investi}} \right) \times 100$$

> **Rappel** : Pour toute modification manuelle, fais-la sur ton PC, puis envoie-la sur GitHub (`git push`). Le robot reprendra sa routine dès le lundi suivant.


# Gestion des Achats Ponctuels (Hors DCA)

Pour intégrer un achat réalisé manuellement (hors automatisme du 16 du mois), aucune modification du code Python n'est requise. Il suffit de mettre à jour le registre d'état pour que le prochain rapport intègre vos nouvelles parts.

## Procédure de mise à jour manuelle

Le script utilise le fichier `portfolio_state.csv` comme source de vérité pour vos possessions. Si vous effectuez un achat (exemple : 1 action Air Liquide à 170 € frais inclus) :

1. **Ouverture du fichier** : Ouvrez `portfolio_state.csv` avec un éditeur de texte ou Excel.
2. **Identification** : Repérez la ligne correspondant à l'actif, ici `AI.PA`.
3. **Mise à jour des quantités** : Modifiez la valeur `Quantity`. 
   * *Exemple : passez de 1.0 à 2.0.*
4. **Mise à jour de l'investissement** : Ajoutez le prix d'achat (frais inclus) au montant `Total_Invested` existant.
   * *Calcul : $158.87 + 170.00 = 328.87$*
5. **Synchronisation** : Enregistrez le fichier et poussez la modification sur votre dépôt GitHub :
   ```bash
   git add portfolio_state.csv
   git commit -m "MAJ : Achat ponctuel AI.PA"
   git push