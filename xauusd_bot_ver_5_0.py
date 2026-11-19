# -*- coding: utf-8 -*-
"""
XAUUSD BOT V5.0 - Analyse + exécution MetaTrader 5 (Exness)
===========================================================================
À chaque clôture de bougie M5 :
  1. lit les dernières bougies (par défaut depuis MT5 : mêmes prix que votre courtier) ;
  2. calcule EMA20, EMA50, RSI(14), ATR(14) ;
  3. détecte une entrée (achat ou vente) ;
  4. vérifie les FILTRES DE BOUGIES (voir plus bas) : un signal bloqué n'ouvre aucun ordre ;
  5. ouvre l'ordre sur MT5 avec LOT, SL et TP2 FIXES (en dollars, modifiables ci-dessous) ;
  6. suit le trade : au TP1, ferme une partie et remonte le stop au point d'entrée ;
  7. enregistre dans le journal CSV UNIQUEMENT les trades ouverts puis fermés (stop, TP, fermeture
     manuelle ou par le bot), avec le TOTAL des profits en dernière ligne.

FILTRES DE BOUGIES (un signal est bloqué si l'un d'eux s'applique) :
  - une des PATTERN_LOOKBACK dernières bougies fermées est un DOJI, un HAMMER ou une SHOOTING STAR ;
  - ACHAT alors que la bougie du signal est rouge (baissière) ;
  - VENTE alors que la bougie du signal est verte (haussière) ;
  - ACHAT si la bougie qui vient de s'ouvrir n'est pas DÉJÀ verte, VENTE si elle n'est pas DÉJÀ rouge
    (un prix égal à l'ouverture ou une bougie illisible bloque aussi : il faut une couleur claire).

SÉCURITÉS (à garder) :
  - DRY_RUN = True  : SIMULATION, aucun ordre envoyé. Passez à False seulement après des tests.
  - ALLOW_LIVE = False : refuse de fonctionner sur un compte RÉEL.
  - une seule position à la fois et limite de perte journalière.

PRÉREQUIS : Windows, MetaTrader 5 d'Exness OUVERT et connecté, bouton "Algo Trading" vert.
    pip install MetaTrader5 pandas requests

Lancement : python xauusd_bot_ver_5_0.py            (boucle continue)
            python xauusd_bot_ver_5_0.py --once      (une seule analyse)

Aucun gain n'est garanti. Testez longtemps en démo. Ce n'est pas un conseil financier.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

try:
    import requests
except ImportError:          # nécessaire seulement si DATA_SOURCE = "TWELVEDATA"
    requests = None

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

# ============================================================================
# PARAMÈTRES (modifiables)
# ============================================================================
# --- Sécurité ---
DRY_RUN = True               # True = simulation (aucun ordre). False = ordres envoyés au compte connecté.
ALLOW_LIVE = False           # False = refuse un compte réel
MAX_DAILY_LOSS_USD = 150     # plus de nouveaux trades si la perte du jour dépasse ce montant ($)
MAGIC = 26111801             # identifiant des ordres de ce programme
DEVIATION = 30               # glissement maximal accepté (points)

# --- Lot, stop et objectifs FIXES (changez-les quand vous voulez) ---
LOT = 0.05                   # taille fixe de chaque trade
SL_USD = 50.0                # perte maximale du trade, en dollars
TP1_USD = 50.0               # TP1 : gain en dollars (une partie de la position est fermée)
TP2_USD = 75.0               # TP2 : gain en dollars (fermeture du reste, posé chez le courtier)
TP1_CLOSE_FRACTION = 0.5     # fraction cible ; arrondie au pas MT5 (0.05 lot / 0.01 -> 0.02 lot = 40 %)
CONTRACT_SIZE = 100.0        # onces par lot (corrigé automatiquement depuis MT5)
LOT_STEP = 0.01              # pas de lot (corrigé automatiquement depuis MT5)

# --- Filtres de bougies ---
PATTERN_LOOKBACK = 3         # nombre de dernières bougies fermées contrôlées (1 = seulement la dernière)
DOJI_BODY_RATIO = 0.10       # doji : corps <= 10 % de la taille de la bougie
WICK_BODY_RATIO = 2.0        # hammer / shooting star : grande mèche >= 2 x le corps
SMALL_WICK_RATIO = 0.15      # ... et petite mèche opposée <= 15 % de la taille de la bougie
REQUIRE_SIGNAL_CANDLE_COLOR = True   # ACHAT seulement si bougie verte, VENTE seulement si rouge
CHECK_LIVE_CANDLE = True     # ACHAT seulement si la bougie qui vient de s'ouvrir est déjà verte, VENTE si déjà rouge

# --- Données ---
DATA_SOURCE = "MT5"          # "MT5" (recommandé) ou "TWELVEDATA"
MT5_SYMBOL = "XAUUSDm"       # nom exact dans Market Watch (XAUUSDm en Standard, XAUUSD en Pro/Raw)
TD_SYMBOL = "XAU/USD"        # utilisé seulement avec Twelve Data
API_KEY = os.environ.get("TWELVEDATA_API_KEY", "")  # clé chargée depuis l’environnement, jamais codée en dur
TD_API_URL = "https://api.twelvedata.com/time_series"
BAR_MINUTES = 5
OUTPUTSIZE = 300             # nombre de bougies lues
DELAY_AFTER_CLOSE = 4        # secondes d'attente après la clôture
STALE_MINUTES = 15           # au-delà, données périmées (marché fermé ?) : aucun signal

# --- Stratégie ---
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
ATR_PERIOD = 14
BREAKOUT_LOOKBACK = 20
MAX_BARS_ACTIVE = 36         # un signal expire après 36 bougies M5 (3 h)
RSI_MIN_FOR_SHORT = 30
RSI_MAX_FOR_LONG = 70

# --- Interrupteurs de stratégie (True = activé, False = désactivé) ---
ENABLE_NEW_YORK_SESSION = False       # Session UTC 13:00-21:00 ; True pour la réactiver
NEW_YORK_START_UTC = 13
NEW_YORK_END_UTC = 21
ENABLE_BUY_EMA20_PULLBACK = False     # Rebond EMA20 en ACHAT ; True pour le réactiver

# --- Journal CSV (uniquement les trades) ---
LOG_DIR = Path(r"C:\Users\USERTEST\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
LOG_NAME = "signals_log.csv"
CSV_DELIMITER = ";"          # ";" pour Excel en français (",": Excel anglais)
CSV_DECIMAL = ","            # "," pour Excel en français ("." : Excel anglais)

TP1_R = TP2_R = 0.0          # objectifs en multiples du risque (calculés par refresh_ratios)


def refresh_ratios():
    """Recalcule TP1/TP2 en multiples de R à partir des montants en dollars."""
    global TP1_R, TP2_R
    TP1_R, TP2_R = TP1_USD / SL_USD, TP2_USD / SL_USD


refresh_ratios()


def usd_to_points(usd):
    """Convertit un montant en dollars en distance de prix (points) pour le lot fixe."""
    return usd / (LOT * CONTRACT_SIZE)


def tp1_fraction():
    """Part réellement fermée au TP1 (arrondie au pas de lot)."""
    close_lot = math.floor(LOT * TP1_CLOSE_FRACTION / LOT_STEP + 1e-9) * LOT_STEP
    if close_lot < LOT_STEP - 1e-9 or LOT - close_lot < LOT_STEP - 1e-9:
        return 0.0
    return close_lot / LOT


# ============================================================================
# STRUCTURES
# ============================================================================
@dataclass
class Signal:
    time: pd.Timestamp
    side: str                # "VENTE" ou "ACHAT"
    setup: str
    entry: float
    stop: float
    initial_stop: float
    tp1: float
    tp2: float
    risk: float
    stage: int = 0           # 0 = en cours, 1 = TP1 atteint (stop au point d'entrée)
    bars: int = 0
    ticket: int | None = None
    trade_id: str = ""
    risk_money: float | None = None   # = SL_USD
    last_processed_bar: pd.Timestamp | None = None  # dernière bougie M5 déjà traitée
    tp1_pending: bool = False    # TP1 touché mais exécution MT5 pas encore confirmée
    initial_volume: float = 0.0  # volume réellement ouvert, pour rendre TP1 idempotent
    tp1_partial_done: bool = False  # réduction TP1 déjà exécutée


# ============================================================================
# DONNÉES
# ============================================================================
def fetch_candles_mt5():
    """Bougies M5 FERMÉES depuis MT5 (heure du serveur du courtier). Retourne (df, âge en minutes)."""
    rates = mt5.copy_rates_from_pos(MT5_SYMBOL, mt5.TIMEFRAME_M5, 1, OUTPUTSIZE)   # 1 = dernière bougie fermée
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 : aucune bougie reçue ({mt5.last_error()})")
    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df[["datetime", "open", "high", "low", "close"]].astype(
        {"open": float, "high": float, "low": float, "close": float}
    ).reset_index(drop=True)
    tick = mt5.symbol_info_tick(MT5_SYMBOL)
    ref = tick.time if tick else time.time()
    age_min = (ref - (int(rates[-1]["time"]) + BAR_MINUTES * 60)) / 60
    return df, age_min


def fetch_candles_twelvedata(api_key):
    """Bougies M5 fermées depuis Twelve Data (heure UTC). Retourne (df, âge en minutes)."""
    if requests is None:
        raise RuntimeError("Le module 'requests' est manquant (pip install requests).")
    params = {"symbol": TD_SYMBOL, "interval": "5min", "outputsize": OUTPUTSIZE, "timezone": "UTC",
              "order": "ASC", "format": "JSON", "apikey": api_key}
    resp = requests.get(TD_API_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError(f"Erreur Twelve Data : {data.get('message', data)}")
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)
    now = pd.Timestamp(datetime.now(timezone.utc))
    df = df[df["datetime"] + pd.Timedelta(minutes=BAR_MINUTES) <= now].reset_index(drop=True)
    age_min = (now - (df["datetime"].iloc[-1] + pd.Timedelta(minutes=BAR_MINUTES))).total_seconds() / 60
    return df, age_min


def fetch_candles(api_key=None):
    if DATA_SOURCE == "MT5":
        return fetch_candles_mt5()
    return fetch_candles_twelvedata(api_key)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """EMA20, EMA50, RSI(14) et ATR(14) (lissage de Wilder pour RSI/ATR)."""
    df = df.copy()
    close, high, low = df["close"], df["high"], df["low"]
    df["ema_fast"] = close.ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=EMA_SLOW, adjust=False).mean()

    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + avg_gain / avg_loss)

    prev_close = close.shift()
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    df["atr"] = true_range.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    return df


# ============================================================================
# STRATÉGIE
# ============================================================================
def trend_state(df: pd.DataFrame) -> str:
    last, ref = df.iloc[-1], df.iloc[-4]
    if (last["close"] < last["ema_slow"] and last["ema_fast"] < last["ema_slow"]
            and last["ema_slow"] < ref["ema_slow"]):
        return "BAISSIERE"
    if (last["close"] > last["ema_slow"] and last["ema_fast"] > last["ema_slow"]
            and last["ema_slow"] > ref["ema_slow"]):
        return "HAUSSIERE"
    return "NEUTRE"


def make_signal(bar_time, side, setup, entry):
    """Signal à lot, stop et objectifs FIXES (distances déduites des montants en dollars)."""
    sign = -1 if side == "VENTE" else 1
    risk = usd_to_points(SL_USD)
    stop = entry - sign * risk
    return Signal(time=bar_time, side=side, setup=setup, entry=entry, stop=stop, initial_stop=stop,
                  tp1=entry + sign * usd_to_points(TP1_USD), tp2=entry + sign * usd_to_points(TP2_USD),
                  risk=risk, risk_money=SL_USD)


def candle_pattern(o, h, l, c):
    """Reconnaît DOJI, HAMMER ou SHOOTING STAR (sinon None)."""
    rng = h - l
    if rng <= 0:
        return "DOJI"
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if body <= DOJI_BODY_RATIO * rng:
        return "DOJI"
    if lower >= WICK_BODY_RATIO * body and upper <= SMALL_WICK_RATIO * rng:
        return "HAMMER (marteau)"
    if upper >= WICK_BODY_RATIO * body and lower <= SMALL_WICK_RATIO * rng:
        return "SHOOTING STAR (étoile filante)"
    return None


def candle_filter_reason(df: pd.DataFrame, side: str) -> str:
    """Retourne la raison du blocage (texte) ou '' si les bougies autorisent le trade."""
    last = df.iloc[-1]
    if REQUIRE_SIGNAL_CANDLE_COLOR:
        if side == "ACHAT" and last["close"] <= last["open"]:
            return "bougie du signal rouge (baissière) ou neutre : ACHAT refusé"
        if side == "VENTE" and last["close"] >= last["open"]:
            return "bougie du signal verte (haussière) ou neutre : VENTE refusée"
    for _, bar in df.iloc[-PATTERN_LOOKBACK:].iterrows():
        pattern = candle_pattern(bar["open"], bar["high"], bar["low"], bar["close"])
        if pattern:
            return f"{pattern} sur la bougie de {bar['datetime']:%H:%M}"
    return ""


LAST_BLOCK = ""   # raison du dernier signal bloqué par un filtre (affichage)


def detect_signal(df: pd.DataFrame):
    """Analyse la dernière bougie fermée. Retourne (Signal | None, tendance)."""
    global LAST_BLOCK
    LAST_BLOCK = ""
    last = df.iloc[-1]
    rsi, close, open_ = last["rsi"], last["close"], last["open"]
    trend = trend_state(df)
    prev3 = df.iloc[-4:-1]
    prior = df.iloc[-(BREAKOUT_LOOKBACK + 1):-1]

    side = setup = None
    if trend == "BAISSIERE" and rsi > RSI_MIN_FOR_SHORT:
        reclaimed = (prev3["close"] > prev3["ema_fast"]).any()
        if reclaimed and close < last["ema_fast"] and close < open_:
            side, setup = "VENTE", "Rejet sous l'EMA20 (rebond)"
        elif close < prior["low"].min():
            side, setup = "VENTE", f"Cassure du plus bas des {BREAKOUT_LOOKBACK} bougies"
    elif trend == "HAUSSIERE" and rsi < RSI_MAX_FOR_LONG:
        reclaimed = (prev3["close"] < prev3["ema_fast"]).any()
        if ENABLE_BUY_EMA20_PULLBACK and reclaimed and close > last["ema_fast"] and close > open_:
            side, setup = "ACHAT", "Rebond sur l'EMA20 (repli)"
        elif close > prior["high"].max():
            side, setup = "ACHAT", f"Cassure du plus haut des {BREAKOUT_LOOKBACK} bougies"
    if side is None:
        return None, trend

    # Blocage de la session New York selon l'heure UTC de la bougie du signal.
    # Le même filtre est utilisé en direct et dans le backtest.
    signal_hour_utc = int(last["datetime"].hour)
    if (not ENABLE_NEW_YORK_SESSION
            and NEW_YORK_START_UTC <= signal_hour_utc < NEW_YORK_END_UTC):
        LAST_BLOCK = (f"{side} bloqué : session New York désactivée "
                      f"({NEW_YORK_START_UTC:02d}:00-{NEW_YORK_END_UTC:02d}:00 UTC)")
        return None, trend

    reason = candle_filter_reason(df, side)
    if reason:
        LAST_BLOCK = f"{side} bloqué : {reason}"
        return None, trend
    return make_signal(last["datetime"], side, setup, close), trend


def manage_active(sig: Signal, df: pd.DataFrame):
    """
    Suit un signal sur les bougies fermées postérieures à son entrée.
    Retourne (liste d'événements (texte, type), signal_terminé).
    Prudence : si stop et objectif sont touchés dans la même bougie, le stop passe en premier.
    """
    events = []
    short = sig.side == "VENTE"
    eligible = df[df["datetime"] > sig.time]
    if sig.last_processed_bar is not None:
        eligible = eligible[eligible["datetime"] > sig.last_processed_bar]
    for _, bar in eligible.iterrows():
        sig.last_processed_bar = bar["datetime"]
        sig.bars += 1
        if short:
            stop_hit, tp1_hit, tp2_hit = bar["high"] >= sig.stop, bar["low"] <= sig.tp1, bar["low"] <= sig.tp2
        else:
            stop_hit, tp1_hit, tp2_hit = bar["low"] <= sig.stop, bar["high"] >= sig.tp1, bar["high"] >= sig.tp2

        if stop_hit:
            if sig.stage == 0:
                events.append((f"SORTIE : stop touché à {sig.stop:.2f} (-{SL_USD:g} $)", "STOP"))
            else:
                events.append((f"SORTIE : retour au point d'entrée {sig.stop:.2f} (reste à 0R)", "BREAKEVEN"))
            return events, True
        if tp2_hit:
            events.append((f"SORTIE : TP2 atteint à {sig.tp2:.2f} (+{TP2_USD:g} $). Fermeture du reste.", "TP2"))
            return events, True
        if tp1_hit and sig.stage == 0:
            sig.stage = 1
            sig.stop = sig.entry
            events.append((f"TP1 atteint à {sig.tp1:.2f} ({TP1_USD:g} $) : encaissez ~{tp1_fraction():.0%} "
                           f"et remontez le stop à {sig.entry:.2f}.", "TP1"))
            # OHLC ne révèle pas l'ordre des ticks : TP1 puis retour au BE dans la même bougie
            # est traité prudemment comme un break-even.
            be_same_bar = (bar["low"] <= sig.entry) if not short else (bar["high"] >= sig.entry)
            if be_same_bar:
                events.append((f"SORTIE : retour au break-even dans la bougie du TP1 ({sig.entry:.2f}).", "BREAKEVEN"))
                return events, True
        if sig.bars >= MAX_BARS_ACTIVE:
            events.append((f"SORTIE : signal expiré après {MAX_BARS_ACTIVE} bougies. Fermeture.", "EXPIRE"))
            return events, True
    return events, False


# ============================================================================
# EXÉCUTION MT5
# ============================================================================
def mt5_log(msg):
    print(f"[MT5] {msg}")


def mt5_connect():
    """Se connecte au terminal MT5 ouvert. Refuse un compte réel si ALLOW_LIVE = False."""
    global CONTRACT_SIZE, LOT_STEP
    if mt5 is None:
        mt5_log("Le module MetaTrader5 est manquant : pip install MetaTrader5 (Windows uniquement).")
        return False
    if not mt5.initialize():
        mt5_log(f"Échec de connexion : {mt5.last_error()} (MT5 est-il ouvert et connecté ?)")
        return False
    acc = mt5.account_info()
    if acc is None:
        mt5_log("Compte introuvable.")
        return False
    is_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    mt5_log(f"Compte {acc.login} ({'DÉMO' if is_demo else 'RÉEL'}) | solde {acc.balance:.2f} {acc.currency}")
    if str(acc.currency).upper() != "USD":
        mt5_log(f"ATTENTION : compte en {acc.currency}, alors que SL_USD/TP_USD sont paramétrés en dollars. "
                "Le risque monétaire n'est pas garanti identique à la devise du compte.")
    if not is_demo and not ALLOW_LIVE:
        mt5_log("Compte réel détecté : refusé (ALLOW_LIVE = False).")
        mt5.shutdown()
        return False
    if not mt5.symbol_select(MT5_SYMBOL, True):
        mt5_log(f"Symbole {MT5_SYMBOL} introuvable. Vérifiez le nom dans Market Watch.")
        mt5.shutdown()
        return False
    info = mt5.symbol_info(MT5_SYMBOL)
    CONTRACT_SIZE = float(getattr(info, "trade_contract_size", CONTRACT_SIZE) or CONTRACT_SIZE)
    LOT_STEP = float(getattr(info, "volume_step", LOT_STEP) or LOT_STEP)
    mt5_log(f"Lot fixe {LOT} | SL {SL_USD:g} $ = {usd_to_points(SL_USD):.2f} pts | "
            f"TP1 {TP1_USD:g} $ = {usd_to_points(TP1_USD):.2f} pts | TP2 {TP2_USD:g} $ = {usd_to_points(TP2_USD):.2f} pts "
            f"(contrat {CONTRACT_SIZE:g})")
    return True


def get_positions():
    pos = mt5.positions_get(symbol=MT5_SYMBOL)
    return [p for p in (pos or []) if p.magic == MAGIC]


def daily_loss_reached():
    """Limite journalière basée sur minuit UTC ; inclut réalisé + flottant des positions EA."""
    tick = mt5.symbol_info_tick(MT5_SYMBOL)
    now_ts = int(tick.time) if tick else int(time.time())
    now_utc = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start_utc, now_utc) or []
    realized = sum(float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0))
                   for d in deals if d.magic == MAGIC and getattr(d, "symbol", MT5_SYMBOL) == MT5_SYMBOL)
    floating = sum(float(p.profit) + float(getattr(p, "swap", 0.0)) for p in get_positions())
    pnl = realized + floating
    if pnl <= -MAX_DAILY_LOSS_USD:
        mt5_log(f"Limite journalière atteinte (réalisé {realized:.2f} + flottant {floating:.2f} = {pnl:.2f} $).")
        return True
    return False


def fixed_lot():
    """Quantifie le lot sans jamais l'augmenter silencieusement au minimum broker."""
    info = mt5.symbol_info(MT5_SYMBOL) if mt5 is not None else None
    if info is None or LOT <= 0:
        return 0.0
    step = float(info.volume_step)
    vmin, vmax = float(info.volume_min), float(info.volume_max)
    if step <= 0 or LOT < vmin - 1e-9 or LOT > vmax + 1e-9:
        mt5_log(f"Lot demandé {LOT:g} hors limites broker [{vmin:g}, {vmax:g}] : ordre refusé.")
        return 0.0
    lot = math.floor(LOT / step + 1e-9) * step
    digits = max(0, len(f"{step:.8f}".rstrip("0").split(".")[-1]))
    lot = round(lot, digits)
    return lot if lot >= vmin - 1e-9 else 0.0


def _filling_mode():
    mode = mt5.symbol_info(MT5_SYMBOL).filling_mode
    if mode & 1:
        return mt5.ORDER_FILLING_FOK
    if mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def _send(request):
    """Envoie un ordre et accepte DONE ou DONE_PARTIAL ; le caller doit vérifier le volume exécuté."""
    result = mt5.order_send(request)
    accepted = {getattr(mt5, "TRADE_RETCODE_DONE", -1),
                getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -2)}
    if result is None or result.retcode not in accepted:
        mt5_log(f"Ordre refusé/non exécuté : {result.retcode if result else mt5.last_error()} "
                f"{result.comment if result else ''}")
        return None
    if result.retcode == getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -2):
        mt5_log(f"Exécution partielle confirmée : volume={getattr(result, 'volume', '?')}")
    return result


def live_candle_ok(side):
    """ACHAT seulement si la bougie qui vient de s'ouvrir est DÉJÀ verte (prix > ouverture),
    VENTE seulement si elle est DÉJÀ rouge (prix < ouverture). Égalité ou lecture impossible : refus."""
    if mt5 is None:
        return False, "MT5 indisponible : impossible de lire la bougie en cours"
    cur = mt5.copy_rates_from_pos(MT5_SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
    tick = mt5.symbol_info_tick(MT5_SYMBOL)
    if cur is None or len(cur) == 0 or tick is None:
        return False, "bougie en cours illisible : ordre refusé par prudence"
    open_cur, price = float(cur[0]["open"]), float(tick.bid)
    detail = f"(ouverture {open_cur:.2f}, prix {price:.2f})"
    if side == "ACHAT":
        if price > open_cur:
            return True, ""
        etat = "rouge" if price < open_cur else "neutre"
        return False, f"bougie en cours {etat} {detail} : ACHAT refusé, il faut une bougie déjà verte"
    if price < open_cur:
        return True, ""
    etat = "verte" if price > open_cur else "neutre"
    return False, f"bougie en cours {etat} {detail} : VENTE refusée, il faut une bougie déjà rouge"


def open_trade(side, comment="XAU M5 bot"):
    """
    Ouvre une position au marché ("ACHAT" ou "VENTE") avec le LOT fixe, un stop de SL_USD et un TP de
    TP2_USD posés chez le courtier (distances calculées depuis le prix du courtier).
    Retourne le ticket, ou None (aussi en simulation).
    """
    if get_positions():
        mt5_log("Une position est déjà ouverte : nouveau signal ignoré.")
        return None
    if daily_loss_reached():
        return None

    tick, info = mt5.symbol_info_tick(MT5_SYMBOL), mt5.symbol_info(MT5_SYMBOL)
    if tick is None or info is None:
        mt5_log("Cotation ou informations du symbole indisponibles : ordre annulé.")
        return None
    buy = side == "ACHAT"
    price = tick.ask if buy else tick.bid
    if price is None or price <= 0:
        mt5_log("Prix d'exécution invalide : ordre annulé.")
        return None
    lot = fixed_lot()
    if lot <= 0:
        return None
    sign = 1 if buy else -1
    sl_dist, tp_dist = usd_to_points(SL_USD), usd_to_points(TP2_USD)
    sl = round(price - sign * sl_dist, info.digits)
    tp = round(price + sign * tp_dist, info.digits)

    min_dist = info.trade_stops_level * info.point
    if sl_dist < min_dist or tp_dist < min_dist:
        mt5_log(f"Distance stop/TP ({sl_dist:.2f} / {tp_dist:.2f} pts) inférieure au minimum du courtier "
                f"({min_dist:.2f}) : ordre annulé. Augmentez SL_USD/TP2_USD ou diminuez LOT.")
        return None

    mt5_log(f"{side} {lot} lot {MT5_SYMBOL} @ {price} | SL {sl} ({SL_USD:g} $) | TP {tp} ({TP2_USD:g} $)")
    if DRY_RUN:
        mt5_log("SIMULATION (DRY_RUN) : aucun ordre envoyé.")
        return None

    result = _send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": MT5_SYMBOL, "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
        "price": price, "sl": sl, "tp": tp, "deviation": DEVIATION, "magic": MAGIC,
        "comment": comment, "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling_mode(),
    })
    if result is None:
        return None
    # MT5 peut retourner un order ticket différent du position ticket : identifier la position réelle.
    for _ in range(5):
        matches = [p for p in get_positions()
                   if (p.type == (mt5.POSITION_TYPE_BUY if buy else mt5.POSITION_TYPE_SELL))]
        if matches:
            actual = max(matches, key=lambda p: getattr(p, "time", 0))
            mt5_log(f"Position confirmée : ticket={actual.ticket}, volume réellement ouvert={actual.volume:.2f}.")
            return actual.ticket
        time.sleep(0.2)
    mt5_log("Ordre accepté mais aucune position correspondante n'a été retrouvée : suivi automatique refusé.")
    return None


def sync_signal_with_position(sig: Signal):
    """Aligne les niveaux suivis sur le prix et le volume réellement exécutés."""
    for pos in get_positions():
        if pos.ticket == sig.ticket:
            sign = 1 if sig.side == "ACHAT" else -1
            sig.entry = pos.price_open
            sig.stop = sig.initial_stop = pos.sl
            sig.tp2 = pos.tp
            sig.tp1 = pos.price_open + sign * usd_to_points(TP1_USD)
            sig.initial_volume = float(pos.volume)
            return


def handle_tp1(sig: Signal | None = None):
    """TP1 idempotent : si le partiel est déjà exécuté, les reprises ne font que poser le SL au BE."""
    if sig is None:
        mt5_log("TP1 refusé : état du trade absent.")
        return False
    if DRY_RUN:
        sig.tp1_partial_done = True
        mt5_log(f"SIMULATION : TP1, fermerait {tp1_fraction():.0%} et remonterait le stop au point d'entrée.")
        return True

    info = mt5.symbol_info(MT5_SYMBOL)
    if info is None:
        mt5_log("TP1 impossible : informations du symbole indisponibles.")
        return False
    pos = next((p for p in get_positions() if p.ticket == sig.ticket), None)
    if pos is None:
        mt5_log("TP1 annulé : position introuvable.")
        return False

    step, vmin = float(info.volume_step), float(info.volume_min)
    initial = float(sig.initial_volume or fixed_lot())
    if step <= 0 or initial <= 0:
        mt5_log("TP1 impossible : volume initial ou pas de lot invalide.")
        return False
    target_close = math.floor(initial * TP1_CLOSE_FRACTION / step + 1e-9) * step
    target_remaining = round(initial - target_close, 8)
    tolerance = max(step * 0.25, 1e-8)
    current_volume = float(pos.volume)
    close_vol = math.floor(max(0.0, current_volume - target_remaining) / step + 1e-9) * step

    # Si un ordre partiel a été exécuté avant une erreur, ne fermer que le complément manquant.
    if close_vol >= vmin - 1e-9 and current_volume - close_vol >= vmin - 1e-9:
        tick = mt5.symbol_info_tick(MT5_SYMBOL)
        if tick is None:
            mt5_log("TP1 impossible : cotation indisponible.")
            return False
        buy = pos.type == mt5.POSITION_TYPE_BUY
        result = _send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": MT5_SYMBOL, "position": pos.ticket,
            "volume": round(close_vol, 8),
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if buy else tick.ask, "deviation": DEVIATION, "magic": MAGIC,
            "comment": "TP1 partiel", "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling_mode(),
        })
        if result is None:
            return False
        time.sleep(0.25)
        pos = next((p for p in get_positions() if p.ticket == sig.ticket), None)
        if pos is None or float(pos.volume) > target_remaining + tolerance:
            mt5_log("TP1 partiel non confirmé jusqu'au volume cible ; aucune confirmation de BE.")
            return False
    elif current_volume > target_remaining + tolerance:
        mt5_log("TP1 impossible : volume résiduel incompatible avec le minimum/pas broker.")
        return False

    # Le volume cible est atteint : les tentatives suivantes ne refont jamais le partiel.
    sig.tp1_partial_done = True
    pos = next((p for p in get_positions() if p.ticket == sig.ticket), None)
    if pos is None:
        return False
    point = float(info.point)
    if abs(float(pos.sl) - float(pos.price_open)) > point * 2:
        mod = _send({"action": mt5.TRADE_ACTION_SLTP, "symbol": MT5_SYMBOL, "position": pos.ticket,
                     "sl": pos.price_open, "tp": pos.tp})
        if mod is None:
            mt5_log("Réduction TP1 faite ; déplacement du SL au BE à réessayer.")
            return False
        time.sleep(0.2)
    verified = next((p for p in get_positions() if p.ticket == sig.ticket), None)
    if verified is None or abs(float(verified.sl) - float(verified.price_open)) > point * 2:
        mt5_log("Réduction TP1 faite ; SL au BE non confirmé. Nouvelle tentative sans seconde réduction.")
        return False
    mt5_log(f"TP1 confirmé : volume restant {verified.volume:.2f} lot ; SL vérifié au BE {verified.price_open:.2f}.")
    return True


def close_all(comment="Fermeture"):
    """Ferme toutes les positions de ce programme (fin de signal, expiration, arrêt)."""
    if DRY_RUN:
        mt5_log("SIMULATION : fermerait la position restante.")
        return
    for pos in get_positions():
        buy = pos.type == mt5.POSITION_TYPE_BUY
        tick = mt5.symbol_info_tick(MT5_SYMBOL)
        mt5_log(f"Fermeture de la position {pos.ticket} ({pos.volume} lot)")
        _send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": MT5_SYMBOL, "position": pos.ticket,
            "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if buy else tick.ask, "deviation": DEVIATION, "magic": MAGIC,
            "comment": comment, "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling_mode(),
        })


def position_result(ticket):
    """Résultat réel d'une position FERMÉE d'après l'historique MT5 : profit (commissions et swap inclus),
    motif de fermeture et heure. Retourne None si la position n'est pas (encore) fermée."""
    if mt5 is None or ticket is None:
        return None
    reasons = {getattr(mt5, "DEAL_REASON_SL", 4): "Stop loss touché",
               getattr(mt5, "DEAL_REASON_TP", 5): "Take profit touché",
               getattr(mt5, "DEAL_REASON_CLIENT", 0): "Fermeture manuelle",
               getattr(mt5, "DEAL_REASON_MOBILE", 1): "Fermeture manuelle",
               getattr(mt5, "DEAL_REASON_WEB", 2): "Fermeture manuelle",
               getattr(mt5, "DEAL_REASON_EXPERT", 3): "Fermé par le bot",
               getattr(mt5, "DEAL_REASON_SO", 6): "Stop out (marge)"}
    for _ in range(4):
        deals = mt5.history_deals_get(position=ticket)
        outs = [d for d in (deals or []) if d.entry != mt5.DEAL_ENTRY_IN]
        if outs:
            last = max(outs, key=lambda d: getattr(d, "time", 0))
            return {"profit": sum(d.profit + d.commission + d.swap for d in deals),
                    "label": reasons.get(getattr(last, "reason", None)),
                    "time": pd.Timestamp(getattr(last, "time", 0), unit="s")}
        time.sleep(0.5)
    return None


# ============================================================================
# AFFICHAGE ET JOURNAL
# ============================================================================
RESET, RED, GREEN, YELLOW, CYAN, BOLD = "\033[0m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[1m"

COLUMNS = [
    "Date_Heure", "Clôture", "EMA20", "EMA50", "RSI", "ATR", "Tendance", "Décision", "Type_Signal",
    "ID_Trade", "Sens", "Entrée", "Stop", "TP1", "TP2", "Risque_pts", "Mode", "Ticket_MT5",
    "Date_Sortie", "Type_Sortie", "Résultat_R", "Profit_USD", "Résultat",
]
SORTIE_LABELS = {
    "STOP": "Stop loss touché", "BREAKEVEN": "TP1 puis retour au point d'entrée", "TP2": "Take profit touché",
    "EXPIRE": "Expiration du signal", "BROKER": "Fermé côté courtier",
}


def fmt(x, nd=2):
    """Nombre -> texte (virgule décimale si CSV_DECIMAL = ',')."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    txt = f"{x:.{nd}f}"
    return txt.replace(".", CSV_DECIMAL) if CSV_DECIMAL != "." else txt


def to_float(txt):
    try:
        return float(str(txt).replace(CSV_DECIMAL, "."))
    except ValueError:
        return None


class TradeLog:
    """Journal CSV : UNE ligne par trade (créée à l'ouverture, complétée à la fermeture) et, tout en bas,
    une ligne TOTAL avec la somme des profits dans la colonne Profit_USD."""

    def __init__(self, path):
        self.path = Path(path)
        self.ops = []                       # opérations en attente (réessayées si le fichier est verrouillé)

    def prepare(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f, delimiter=CSV_DELIMITER))
            dec = COLUMNS.index("Décision")
            valid = (bool(rows) and rows[0] == COLUMNS and
                     all(len(r) == len(COLUMNS) and (r[dec].startswith("SIGNAL") or r[dec] == "TOTAL")
                         for r in rows[1:]))
            if not valid:                   # ancien format (ex. une ligne par analyse) : mis de côté
                backup = self.path.with_name(f"{self.path.stem}_ancien_{datetime.now():%Y%m%d_%H%M%S}.csv")
                self.path.rename(backup)
                print(f"Ancien journal renommé : {backup.name}")
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f, delimiter=CSV_DELIMITER).writerow(COLUMNS)

    def add_trade(self, row: dict):
        self.ops.append(("add", row))

    def update_trade(self, trade_id, fields: dict):
        """Complète la ligne de ce trade tant qu'elle est EN COURS (TP1, fermeture, résultat...)."""
        self.ops.append(("update", trade_id, fields))

    def _read(self):
        with self.path.open("r", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f, delimiter=CSV_DELIMITER))
        header = rows[0]
        data = [r for r in rows[1:] if r[header.index("Décision")] != "TOTAL"]
        return header, data

    def _write(self, header, data):
        idx = {c: i for i, c in enumerate(header)}
        out = list(data)
        if data:                            # ligne TOTAL toujours en dernier
            total = sum(v for v in (to_float(r[idx["Profit_USD"]]) for r in data) if v is not None)
            row = [""] * len(header)
            row[idx["Décision"]], row[idx["Profit_USD"]] = "TOTAL", fmt(total)
            out.append(row)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=CSV_DELIMITER)
            w.writerow(header)
            w.writerows(out)
        os.replace(tmp, self.path)

    def flush(self):
        if not self.ops:
            return True
        try:
            if not self.path.exists():
                self.prepare()
            header, data = self._read()
            idx = {c: i for i, c in enumerate(header)}
            for op in self.ops:
                if op[0] == "add":
                    data.append([op[1].get(c, "") for c in header])
                else:
                    _, tid, fields = op
                    for r in data:
                        if r[idx["ID_Trade"]] == tid and r[idx["Résultat"]] == "EN COURS":
                            for k, v in fields.items():
                                r[idx[k]] = v
            self._write(header, data)
            self.ops.clear()
            return True
        except PermissionError:
            print(f"{YELLOW}Journal verrouillé (ouvert dans Excel ?) : fermez-le ou fermez le fichier. "
                  f"L'enregistrement sera rattrapé à la prochaine bougie.{RESET}")
        except OSError as exc:
            print(f"{YELLOW}Journal : écriture impossible ({exc}). Nouvel essai à la prochaine bougie.{RESET}")
        return False

    def mark_orphans(self, resolver):
        """Au démarrage : complète les trades restés EN COURS (programme arrêté) grâce à l'historique MT5."""
        try:
            header, data = self._read()
            idx = {c: i for i, c in enumerate(header)}
            changed = False
            for r in data:
                if r[idx["Résultat"]] == "EN COURS":
                    fields = resolver(dict(zip(header, r)))
                    if fields:
                        for k, v in fields.items():
                            r[idx[k]] = v
                        changed = True
            if changed:
                self._write(header, data)
        except (OSError, ValueError, IndexError):
            pass


LOG = TradeLog(LOG_DIR / LOG_NAME)


def classify(value):
    if value is None:
        return "INCONNU"
    return "GAGNANT" if value > 1e-9 else "PERDANT" if value < -1e-9 else "NUL"


def finalize_trade(sig: Signal, final_kind: str, price: float, bar_close_str: str):
    """Colonnes de sortie d'un trade terminé : résultat réel MT5 si disponible, sinon calcul simulé."""
    frac = tp1_fraction()
    r_virtual = None
    if final_kind == "STOP":
        r_virtual = -1.0
    elif final_kind == "BREAKEVEN":
        r_virtual = frac * TP1_R
    elif final_kind == "TP2":
        r_virtual = frac * TP1_R + (1 - frac) * TP2_R
    elif final_kind == "EXPIRE":
        sign = -1 if sig.side == "VENTE" else 1
        move = sign * (price - sig.entry) / sig.risk
        r_virtual = frac * TP1_R + (1 - frac) * move if sig.stage == 1 else move

    info = position_result(sig.ticket) if sig.ticket is not None else None
    type_sortie = SORTIE_LABELS.get(final_kind, final_kind)
    exit_time = bar_close_str
    if info:                                           # résultat RÉEL lu dans l'historique MT5
        profit = info["profit"]
        r = profit / sig.risk_money if sig.risk_money else r_virtual
        verdict = classify(profit)
        if info["label"] and info["label"] != "Fermé par le bot":
            type_sortie = info["label"]
        exit_time = f"{info['time']:%Y-%m-%d %H:%M}"
    elif sig.ticket is None and r_virtual is not None:  # SIMULATION : résultat estimé
        r, profit = r_virtual, r_virtual * (sig.risk_money or 0.0)
        verdict = classify(profit)
    else:                                              # ordre réel mais historique illisible
        r, profit, verdict = r_virtual, None, classify(r_virtual)
    return {"Date_Sortie": exit_time, "Type_Sortie": type_sortie, "Résultat_R": fmt(r),
            "Profit_USD": fmt(profit), "Résultat": verdict}


def orphan_fields(row: dict):
    """Pour un trade resté EN COURS au redémarrage : lit son résultat dans MT5 s'il est fermé."""
    ticket = row.get("Ticket_MT5", "")
    if not ticket:                                     # trade simulé : plus de suivi possible
        return {"Résultat": "INCONNU (redémarrage)", "Type_Sortie": "Programme redémarré"}
    t = int(ticket)
    if mt5 is not None and any(p.ticket == t for p in get_positions()):
        mt5_log(f"Le trade {row.get('ID_Trade')} (ticket {t}) est encore ouvert : le programme ne le suit plus, "
                f"gérez-le dans MT5 (son stop et son TP restent actifs).")
        return None                                    # reste EN COURS, complété à un prochain démarrage
    info = position_result(t)
    if not info:
        return {"Résultat": "INCONNU (redémarrage)", "Type_Sortie": "Historique introuvable"}
    entry, stop = to_float(row.get("Entrée")), to_float(row.get("Stop"))
    risk_money = SL_USD
    return {"Date_Sortie": f"{info['time']:%Y-%m-%d %H:%M}", "Type_Sortie": info["label"] or "Fermé",
            "Résultat_R": fmt(info["profit"] / risk_money) if risk_money else "",
            "Profit_USD": fmt(info["profit"]), "Résultat": classify(info["profit"])}


def trade_cols(sig: Signal):
    return {"ID_Trade": sig.trade_id, "Sens": sig.side, "Type_Signal": sig.setup,
            "Entrée": fmt(sig.entry), "Stop": fmt(sig.initial_stop), "TP1": fmt(sig.tp1), "TP2": fmt(sig.tp2),
            "Risque_pts": fmt(sig.risk), "Ticket_MT5": "" if sig.ticket is None else str(sig.ticket)}


def print_report(df, trend, new_signal, active, events, stale, sound):
    last = df.iloc[-1]
    t_close = last["datetime"] + pd.Timedelta(minutes=BAR_MINUTES)
    zone = "heure serveur MT5" if DATA_SOURCE == "MT5" else "UTC"
    res, sup = df["high"].iloc[-12:].max(), df["low"].iloc[-12:].min()
    mode = "SIMULATION" if DRY_RUN else "ORDRES RÉELS"

    print("\n" + "=" * 66)
    print(f"{BOLD}XAUUSD M5{RESET} [{mode}] | clôture {t_close:%H:%M} ({zone})")
    print(f"Prix {last['close']:.2f} | EMA20 {last['ema_fast']:.2f} | EMA50 {last['ema_slow']:.2f} "
          f"| RSI {last['rsi']:.1f} | ATR {last['atr']:.2f}")
    print(f"Tendance : {trend} | Résistance 1 h : {res:.2f} | Support 1 h : {sup:.2f}")

    if stale:
        print(f"{YELLOW}Données non à jour (marché fermé ?) : aucun nouveau signal.{RESET}")
    for text, kind in events:
        color = GREEN if kind in ("TP1", "TP2") else RED if kind in ("STOP", "REFUSE") else YELLOW
        print(f"{color}{BOLD}>> {text}{RESET}")
        if sound:
            print("\a", end="")

    if new_signal:
        color = RED if new_signal.side == "VENTE" else GREEN
        print(f"{color}{BOLD}>> NOUVEAU SIGNAL : {new_signal.side}{RESET}  ({new_signal.setup})")
        print(f"   Entrée ~{new_signal.entry:.2f} | Stop {new_signal.stop:.2f} | TP1 {new_signal.tp1:.2f} "
              f"| TP2 {new_signal.tp2:.2f} | Risque {new_signal.risk:.2f} pts")
        if sound:
            print("\a", end="")
    elif active:
        etat = "TP1 déjà pris, stop au point d'entrée" if active.stage == 1 else "en cours"
        print(f"{CYAN}Signal {active.side} {etat} : entrée {active.entry:.2f} | stop {active.stop:.2f} "
              f"| TP1 {active.tp1:.2f} | TP2 {active.tp2:.2f} ({active.bars} bougies){RESET}")
    elif not stale and not events:
        print("Pas de signal sur cette bougie.")
    print("=" * 66, flush=True)


# ============================================================================
# BOUCLE PRINCIPALE
# ============================================================================

def manage_intrabar_tp1(state):
    """Surveille le niveau TP1 entre les clôtures M5 afin de réduire le délai d'exécution."""
    sig = state.get("active")
    if sig is None or sig.stage != 0 or DRY_RUN or sig.ticket is None:
        return
    pos = next((p for p in get_positions() if p.ticket == sig.ticket), None)
    if pos is None:
        return
    tick = mt5.symbol_info_tick(MT5_SYMBOL)
    if tick is None:
        return
    # Achat liquidé au Bid ; vente liquidée à l'Ask.
    executable = float(tick.bid if sig.side == "ACHAT" else tick.ask)
    touched = executable >= sig.tp1 if sig.side == "ACHAT" else executable <= sig.tp1
    if touched:
        sig.tp1_pending = True
        mt5_log(f"TP1 touché en tick à {executable:.2f} ; tentative de réduction immédiate.")
    # Si MT5 a refusé temporairement l'ordre, on retente même après le repli du cours.
    if sig.tp1_pending and handle_tp1(sig):
        sig.stage = 1
        sig.stop = sig.entry
        sig.tp1_pending = False
        LOG.update_trade(sig.trade_id, {"Type_Sortie": "TP1 atteint - partie encaissée"})
        LOG.flush()


def recover_active_position():
    """Reconstruit le suivi minimal d'une position EA encore ouverte après redémarrage."""
    positions = get_positions()
    if not positions:
        return None
    if len(positions) > 1:
        mt5_log(f"ATTENTION : {len(positions)} positions EA ouvertes ; suivi automatique suspendu.")
        return None
    pos = positions[0]
    side = "ACHAT" if pos.type == mt5.POSITION_TYPE_BUY else "VENTE"
    sign = 1 if side == "ACHAT" else -1
    entry = float(pos.price_open)
    sl = float(pos.sl) if pos.sl else entry - sign * usd_to_points(SL_USD)
    risk = abs(entry - sl)
    if risk <= 0:
        mt5_log("Position ouverte retrouvée mais SL absent/invalide : suivi automatique suspendu.")
        return None
    original_volume = fixed_lot()
    stage = 1 if pos.volume < original_volume - 1e-8 or abs(sl-entry) <= mt5.symbol_info(MT5_SYMBOL).point*2 else 0
    tp2 = float(pos.tp) if pos.tp else entry + sign * usd_to_points(TP2_USD)
    recovered_id = f"RECOVER_{pos.ticket}"
    try:
        header, rows = LOG._read()
        idx = {name: j for j, name in enumerate(header)}
        for row in rows:
            if row[idx["Ticket_MT5"]] == str(pos.ticket) and row[idx["Résultat"]] == "EN COURS":
                recovered_id = row[idx["ID_Trade"]]
                break
    except Exception:
        pass
    sig = Signal(time=pd.Timestamp(datetime.fromtimestamp(pos.time, tz=timezone.utc)), side=side,
                 setup="Position récupérée après redémarrage", entry=entry, stop=sl,
                 initial_stop=entry-sign*risk, tp1=entry+sign*usd_to_points(TP1_USD), tp2=tp2,
                 risk=risk, stage=stage, bars=0, ticket=pos.ticket,
                 trade_id=recovered_id, risk_money=SL_USD,
                 last_processed_bar=pd.Timestamp(datetime.now(timezone.utc)),
                 initial_volume=fixed_lot(), tp1_partial_done=(stage == 1))
    mt5_log(f"Position récupérée : ticket {pos.ticket}, {side}, {pos.volume} lot, étape TP1={stage}.")
    return sig

def run_cycle(api_key, state: dict, sound: bool) -> bool:
    """Analyse la dernière bougie fermée. Retourne False s'il n'y a pas de nouvelle bougie."""
    df, age_min = fetch_candles(api_key)
    if len(df) < EMA_SLOW + 10:
        raise RuntimeError("Pas assez de bougies pour calculer les indicateurs.")

    last_time = df["datetime"].iloc[-1]
    if state.get("active") is not None:
        manage_intrabar_tp1(state)
    if state["last_bar"] is not None and last_time <= state["last_bar"]:
        return False
    state["last_bar"] = last_time

    df = add_indicators(df)
    stale = age_min > STALE_MINUTES
    price = df["close"].iloc[-1]
    events, new_signal, closed = [], None, []

    active = state["active"]

    # Position fermée côté courtier (stop, TP ou fermeture manuelle) ?
    if active is not None and active.ticket is not None and not get_positions():
        events.append(("Position fermée côté courtier (stop, TP ou fermeture manuelle).", "BROKER"))
        closed.append((active, "BROKER"))
        state["active"] = active = None

    # Suivi du signal en cours
    if active is not None:
        new_events, finished = manage_active(active, df)
        events.extend(new_events)
        for text, kind in new_events:
            if kind == "TP1":
                if handle_tp1(active):
                    active.stage = 1
                    active.stop = active.entry
                    LOG.update_trade(active.trade_id, {"Type_Sortie": "TP1 atteint - partie encaissée"})
                else:
                    # Garder l'événement en attente : le gestionnaire tick retentera l'exécution.
                    active.stage = 0
                    active.stop = active.initial_stop
                    active.tp1_pending = True
                    mt5_log("TP1 non validé : événement conservé en attente ; nouvelle tentative à chaque contrôle tick.")
            elif kind in ("STOP", "TP2", "BREAKEVEN", "EXPIRE"):
                close_all(f"Fin de signal : {kind}")
        if finished:
            closed.append((active, new_events[-1][1]))
            state["active"] = active = None

    # Nouveau signal (après filtres de bougies)
    trend = trend_state(df)
    block_msg = ""
    if state["active"] is None and not stale:
        sig, trend = detect_signal(df)
        if sig:
            ok, why = live_candle_ok(sig.side) if CHECK_LIVE_CANDLE else (True, "")
            if not ok:
                block_msg = f"{sig.side} bloqué : {why}"
            else:
                ticket = open_trade(sig.side)
                if not DRY_RUN and ticket is None:
                    events.append(("Signal détecté mais ordre non ouvert (voir messages [MT5]) : signal abandonné.",
                                   "REFUSE"))
                else:
                    sig.ticket = ticket
                    sig.trade_id = f"T{last_time:%Y%m%d%H%M}"
                    if ticket is not None:
                        sync_signal_with_position(sig)
                    state["active"] = new_signal = sig
        elif LAST_BLOCK:
            block_msg = LAST_BLOCK
    if block_msg:
        events.append((f"Signal bloqué - {block_msg}", "BLOCK"))

    # ----- Journal CSV : uniquement les trades -----
    last = df.iloc[-1]
    close_str = f"{last_time + pd.Timedelta(minutes=BAR_MINUTES):%Y-%m-%d %H:%M}"
    for sig, kind in closed:                           # trades terminés pendant ce cycle
        LOG.update_trade(sig.trade_id, finalize_trade(sig, kind, price, close_str))
    if new_signal:
        LOG.add_trade({
            "Date_Heure": close_str, "Clôture": fmt(price), "EMA20": fmt(last["ema_fast"]),
            "EMA50": fmt(last["ema_slow"]), "RSI": fmt(last["rsi"], 1), "ATR": fmt(last["atr"]),
            "Tendance": trend, "Décision": f"SIGNAL {new_signal.side}", **trade_cols(new_signal),
            "Mode": "SIMULATION" if DRY_RUN else "ORDRES ENVOYÉS", "Résultat": "EN COURS"})
    LOG.flush()

    print_report(df, trend, new_signal, state["active"] if new_signal is None else None,
                 events, stale, sound)
    return True


def seconds_until_next_close() -> float:
    now = datetime.now(timezone.utc)
    minutes_to_next = BAR_MINUTES - (now.minute % BAR_MINUTES)
    next_close = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_next)
    return (next_close - now).total_seconds() + DELAY_AFTER_CLOSE


def main() -> int:
    global DATA_SOURCE, LOG
    parser = argparse.ArgumentParser(description="Bot XAUUSD M5 : analyse + exécution MT5")
    parser.add_argument("--api-key", default=None, help="Clé Twelve Data (seulement si --source TWELVEDATA)")
    parser.add_argument("--source", choices=["MT5", "TWELVEDATA"], default=None)
    parser.add_argument("--once", action="store_true", help="Une seule analyse puis arrêt")
    parser.add_argument("--no-sound", action="store_true", help="Désactive le bip sonore")
    args = parser.parse_args()
    if args.source:
        DATA_SOURCE = args.source

    api_key = args.api_key or os.environ.get("TWELVEDATA_API_KEY")
    if DATA_SOURCE == "TWELVEDATA" and not api_key:
        print("Clé API Twelve Data manquante : définissez TWELVEDATA_API_KEY ou utilisez --api-key.")
        return 1
    if not mt5_connect():
        return 1

    try:
        LOG.prepare()
    except OSError as exc:
        try:
            here = Path(__file__).resolve().parent
        except NameError:
            here = Path.cwd()
        print(f"{YELLOW}Dossier du journal inaccessible ({exc}). Journal enregistré dans : {here}{RESET}")
        LOG = TradeLog(here / LOG_NAME)
        LOG.prepare()
    LOG.mark_orphans(orphan_fields)
    print(f"Journal des trades : {LOG.path}")

    mode = "SIMULATION : aucun ordre ne sera envoyé" if DRY_RUN else "ORDRES RÉELS envoyés au compte connecté"
    print(f"\nBot XAUUSD M5 démarré | données : {DATA_SOURCE} | {mode}")
    print("Ctrl+C pour arrêter. Les positions ouvertes gardent leur stop et leur TP chez le courtier.")

    state = {"last_bar": None, "active": None}
    # Évite de recréer un trade sur le signal courant et reprend une position EA déjà ouverte.
    try:
        state["active"] = recover_active_position()
    except Exception as exc:
        mt5_log(f"Récupération position impossible : {exc}")
    try:
        while True:
            try:
                got_new_bar = False
                for _ in range(8):                      # attend jusqu'à ~40 s la nouvelle bougie
                    if run_cycle(api_key, state, not args.no_sound):
                        got_new_bar = True
                        break
                    time.sleep(5)
                if not got_new_bar:
                    print("Pas de nouvelle bougie (marché fermé ou données en retard).")
            except Exception as exc:                    # une erreur ne doit pas arrêter le bot
                print(f"{YELLOW}Erreur : {exc}{RESET}")

            if args.once:
                return 0
            wait = seconds_until_next_close()
            print(f"Prochaine analyse dans {int(wait)} s...", flush=True)
            time.sleep(wait)
    except KeyboardInterrupt:
        LOG.flush()
        print("\nArrêt demandé. Journal : " + str(LOG.path))
        print("Rappel : une position ouverte reste active chez le courtier avec son stop et son TP.")
        return 0
    finally:
        if mt5 is not None:
            mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
