"""Chemins, configuration et utilitaires de date partagés."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

CONFIG_FILE = os.path.join(ROOT, "config.json")
LEDGER_FILE = os.path.join(DATA_DIR, "transactions.csv")
RECON_FILE = os.path.join(DATA_DIR, "reconciliation.csv")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
ACTIONS_FILE = os.path.join(DATA_DIR, "corporate_actions.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.csv")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
DASHBOARD_JS = os.path.join(DATA_DIR, "dashboard.js")


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def now_local(cfg):
    return datetime.now(ZoneInfo(cfg.get("timezone", "Europe/Paris")))


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
