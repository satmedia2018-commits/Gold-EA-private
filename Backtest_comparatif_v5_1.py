# -*- coding: utf-8 -*-
"""
Backtest COMPARATIF V5.1  (à placer avec xauusd_bot_ver_5_1.py)
============================================================================
Compare la V5.0 (référence) et plusieurs variantes de la V5.1 sur le MÊME historique, puis juge chacune
selon vos critères :
    OBJECTIF = Profit Factor NET >= 1,50 sur la PREMIÈRE moitié ET sur la SECONDE moitié de la période.

Pour chaque variante, le tableau donne, par période : nombre de trades, PF net et "PF prudent" (p10 =
10e percentile du PF sur 1000 tirages aléatoires des trades : si p10 < 1, le résultat est fragile).

RÈGLES D'HONNÊTETÉ DE CE BACKTEST
  - Entrée à l'open de la bougie suivante ; coûts = spread + glissement ; stop prioritaire si stop et
    objectif sont touchés dans la même bougie.
  - Le contrôle de la bougie qui vient de s'ouvrir (CHECK_LIVE_CANDLE) n'est pas simulé (il faut des ticks).
  - Plus on teste de variantes sur les mêmes données, plus une variante peut "réussir" par hasard.
    Pour limiter ce risque : gardez peu de variantes, utilisez beaucoup de données (BARS = 50000) et
    activez --holdout 0.25 : les 25 % de données les plus récentes ne servent QU'À contrôler, une fois, les
    variantes qui ont réussi sur les deux périodes précédentes.
  - Un résultat positif sur le passé ne garantit rien pour l'avenir.

UTILISATION (Thonny) : réglez les constantes, puis Run. En ligne de commande :
    python Backtest_comparatif_v5_1.py --csv xauusd_m5_cache_MT5.csv --holdout 0.25
"""

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------- RÉGLAGES (modifiables) ----------------------------
SOURCE = "MT5"             # "MT5" (terminal ouvert) ou "TWELVEDATA" (clé : variable TWELVEDATA_API_KEY)
BARS = 20000               # 50 000 bougies M5 = environ 174 jours de cotation continue
SPREAD = 0.30              # spread moyen en dollars (points de prix) : ajustez à votre compte
SLIPPAGE = 0.10            # glissement moyen par trade en dollars
TARGET_PF = 1.50           # votre objectif : PF net minimum sur CHAQUE période
MIN_TRADES_PER_PERIOD = 80  # en dessous, la période est trop petite pour conclure
HOLDOUT = 0.0              # part finale des données gardée pour un contrôle unique (ex. 0.25)
BOOTSTRAP_DRAWS = 1000
TD_API_URL = "https://api.twelvedata.com/time_series"

# Variantes testées : (nom, {paramètre du bot: valeur}). {} = réglages actuels du bot (référence V5.0).
VARIANTS = [
    ("V5.0 (référence)", {}),
    ("A  Filtre volatilité (ATR/stop)", {"ENABLE_ATR_FILTER": True}),
    ("B  Force de tendance (écart EMA)", {"ENABLE_TREND_STRENGTH": True}),
    ("C  Tendance longue (EMA200)", {"ENABLE_HTF_FILTER": True}),
    ("D  Pause 6 bougies après perte", {"COOLDOWN_BARS_AFTER_STOP": 6}),
    ("E  Stop non remonté après TP1", {"MOVE_SL_TO_BE_AT_TP1": False}),
    ("F  A + B", {"ENABLE_ATR_FILTER": True, "ENABLE_TREND_STRENGTH": True}),
    ("G  A + B + C", {"ENABLE_ATR_FILTER": True, "ENABLE_TREND_STRENGTH": True, "ENABLE_HTF_FILTER": True}),
    ("H  A + B + C + D", {"ENABLE_ATR_FILTER": True, "ENABLE_TREND_STRENGTH": True,
                          "ENABLE_HTF_FILTER": True, "COOLDOWN_BARS_AFTER_STOP": 6}),
    ("I  Sorties 1R / 2R (TP2 100 $)", {"TP2_USD": 100.0}),
]


# ------------------------- CHARGEMENT DU BOT ---------------------------------
def load_bot(path=None):
    here = Path(__file__).resolve().parent
    candidates = [Path(path)] if path else [here / "xauusd_bot_ver_5_1.py", here / "xauusd_bot.py"]
    for p in candidates:
        if p.exists():
            spec = importlib.util.spec_from_file_location("bot", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["bot"] = mod
            spec.loader.exec_module(mod)
            print(f"Stratégie chargée depuis : {p.name}")
            if not hasattr(mod, "stop_after_tp1_r"):
                sys.exit("Ce backtest comparatif nécessite xauusd_bot_ver_5_1.py (fonction stop_after_tp1_r).")
            return mod
    sys.exit("Fichier du bot introuvable : placez ce script avec 'xauusd_bot_ver_5_1.py' ou utilisez --bot.")


# ------------------------- DONNÉES -------------------------------------------
def _clean(df):
    required = ["datetime", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans les données : {missing}")
    df = df[required].copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=required)
    df = df.drop_duplicates("datetime", keep="last").sort_values("datetime").reset_index(drop=True)
    bad = ((df["high"] < df[["open", "close", "low"]].max(axis=1)) |
           (df["low"] > df[["open", "close", "high"]].min(axis=1)) |
           (df[["open", "high", "low", "close"]] <= 0).any(axis=1))
    if bad.any():
        examples = df.loc[bad, "datetime"].head(3).astype(str).tolist()
        raise ValueError(f"{int(bad.sum())} bougies OHLC incohérentes. Exemples : {examples}")
    if before - len(df):
        print(f"Nettoyage des données : {before - len(df)} ligne(s) vide(s)/doublon(s) supprimée(s).")
    return df


def download_mt5(bot, n_bars):
    mt5 = bot.mt5
    if mt5 is None:
        sys.exit("Module MetaTrader5 manquant (pip install MetaTrader5) ou utilisez SOURCE = \"TWELVEDATA\".")
    if not mt5.initialize():
        sys.exit(f"Connexion à MT5 impossible : {mt5.last_error()} (MT5 est-il ouvert et connecté ?)")
    if not mt5.symbol_select(bot.MT5_SYMBOL, True):
        mt5.shutdown()
        sys.exit(f"Symbole {bot.MT5_SYMBOL} indisponible dans MT5.")
    info = mt5.symbol_info(bot.MT5_SYMBOL)
    if info is not None:
        bot.CONTRACT_SIZE = float(getattr(info, "trade_contract_size", bot.CONTRACT_SIZE) or bot.CONTRACT_SIZE)
        bot.LOT_STEP = float(getattr(info, "volume_step", bot.LOT_STEP) or bot.LOT_STEP)
    rates = mt5.copy_rates_from_pos(bot.MT5_SYMBOL, mt5.TIMEFRAME_M5, 1, n_bars)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        sys.exit("Aucune bougie reçue de MT5. Ouvrez un graphique XAUUSDm M5 et faites-le défiler vers la "
                 "gauche pour charger l'historique, puis relancez.")
    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    if len(df) < n_bars:
        print(f"Seulement {len(df)} bougies disponibles dans MT5 (demandé : {n_bars}).")
    return _clean(df[["datetime", "open", "high", "low", "close"]])


def download_twelvedata(api_key, n_bars):
    import requests
    frames, end_date, total = [], None, 0
    while total < n_bars:
        size = min(5000, n_bars - total)
        params = {"symbol": "XAU/USD", "interval": "5min", "outputsize": size, "timezone": "UTC",
                  "order": "DESC", "format": "JSON", "apikey": api_key}
        if end_date:
            params["end_date"] = end_date
        resp = requests.get(TD_API_URL, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error" or "values" not in data:
            msg = data.get("message", data)
            if frames:
                print(f"Téléchargement interrompu : {msg}")
                break
            sys.exit(f"Erreur Twelve Data : {msg}")
        df = pd.DataFrame(data["values"])
        frames.append(df)
        total += len(df)
        print(f"  {total} bougies téléchargées...")
        if len(df) < size:
            break
        oldest = pd.to_datetime(df["datetime"].iloc[-1], utc=True)
        end_date = (oldest - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(8)
    return _clean(pd.concat(frames, ignore_index=True))


def get_data(bot, args):
    if args.csv:
        print(f"Lecture de {args.csv}")
        return _clean(pd.read_csv(args.csv))
    cache = Path(f"xauusd_m5_cache_{args.source}.csv")
    if cache.exists() and not args.refresh:
        print(f"Lecture du cache {cache} (option --refresh pour recharger)")
        return _clean(pd.read_csv(cache))
    if args.source == "MT5":
        print(f"Lecture de {args.bars} bougies M5 dans MT5...")
        df = download_mt5(bot, args.bars)
    else:
        key = args.api_key or os.environ.get("TWELVEDATA_API_KEY")
        if not key:
            sys.exit("Clé API manquante : définissez TWELVEDATA_API_KEY ou utilisez --api-key.")
        print(f"Téléchargement de {args.bars} bougies M5 XAU/USD (Twelve Data)...")
        df = download_twelvedata(key, args.bars)
    df.to_csv(cache, index=False)
    print(f"Données enregistrées dans {cache}")
    return df


# ------------------------- SIMULATION ----------------------------------------
def run_backtest(bot, df, spread, slippage):
    """Rejoue le bot (réglages actuels du module) sur df (indicateurs déjà calculés)."""
    n = len(df)
    i = bot.EMA_SLOW + 10
    sign_of = {"VENTE": -1, "ACHAT": 1}
    cost_pts = max(0.0, float(spread)) + max(0.0, float(slippage))
    frac = bot.tp1_fraction()
    cooldown = int(bot.COOLDOWN_BARS_AFTER_STOP)
    trades, blocked = [], {}

    while i < n - 1:
        sig, _ = bot.detect_signal(df.iloc[:i + 1])
        if sig is None:
            if bot.LAST_BLOCK:
                reason = bot.LAST_BLOCK
                key = ("session New York" if "session New York" in reason else
                       "volatilité" if "volatilité" in reason else
                       "tendance faible" if "tendance trop faible" in reason else
                       "tendance EMA200" if "tendance longue" in reason else
                       "couleur du signal" if "bougie du signal" in reason else
                       "doji" if "DOJI" in reason else "hammer" if "HAMMER" in reason else
                       "shooting star" if "SHOOTING" in reason else "autre")
                blocked[key] = blocked.get(key, 0) + 1
            i += 1
            continue

        next_open = float(df.iloc[i + 1]["open"])             # entrée à l'open de la bougie suivante
        sig = bot.make_signal(sig.time, sig.side, sig.setup, next_open)
        future = df.iloc[i + 1:i + 1 + bot.MAX_BARS_ACTIVE]
        events, finished = bot.manage_active(sig, future)
        if not finished or not events:                         # trade non terminé à la fin des données
            break

        kinds = [k for _, k in events]
        final = kinds[-1]
        exit_idx = min(i + sig.bars, n - 1)
        if final == "STOP":
            r = bot.stop_after_tp1_r() if "TP1" in kinds else -1.0
        elif final == "BREAKEVEN":
            r = frac * bot.TP1_R
        elif final == "TP2":
            r = frac * bot.TP1_R + (1.0 - frac) * bot.TP2_R
        else:                                                  # EXPIRE : sortie à la clôture
            move = sign_of[sig.side] * (float(df.iloc[exit_idx]["close"]) - sig.entry) / sig.risk
            r = frac * bot.TP1_R + (1.0 - frac) * move if "TP1" in kinds else move

        r_net = r - cost_pts / sig.risk
        trades.append({
            "signal_time": df.iloc[i]["datetime"], "entree": df.iloc[i + 1]["datetime"],
            "sortie": df.iloc[exit_idx]["datetime"], "sens": sig.side, "setup": sig.setup,
            "bougies": sig.bars, "sortie_type": final, "r_brut": round(r, 6), "r_net": round(r_net, 6),
            "profit_usd_net": round(r_net * bot.SL_USD, 2),
        })
        # Nouvelle décision possible à la clôture de la bougie de sortie ; pause éventuelle après une perte.
        i = exit_idx + (cooldown + 1 if (cooldown > 0 and r_net < 0) else 0)
    return pd.DataFrame(trades), blocked


# ------------------------- STATISTIQUES --------------------------------------
def profit_factor(r):
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return float("inf") if losses <= 0 and wins > 0 else (wins / losses if losses > 0 else 0.0)


def pf_p10(r, draws=BOOTSTRAP_DRAWS, seed=7):
    """10e percentile du PF sur des tirages aléatoires (avec remise) des trades : mesure de fragilité."""
    arr = np.asarray(r, dtype=float)
    if len(arr) < 20:
        return float("nan")
    rng = np.random.default_rng(seed)
    sample = arr[rng.integers(0, len(arr), size=(draws, len(arr)))]
    pos = np.where(sample > 0, sample, 0.0).sum(axis=1)
    neg = -np.where(sample < 0, sample, 0.0).sum(axis=1)
    pf = np.where(neg > 0, pos / np.where(neg > 0, neg, 1.0), np.inf)
    return float(np.percentile(pf, 10))


def metrics(tr, usd_per_r):
    if tr is None or tr.empty:
        return {"n": 0, "pf": 0.0, "p10": float("nan"), "usd": 0.0, "avg": 0.0, "win": 0.0, "dd": 0.0}
    r = tr["r_net"]
    equity = pd.concat([pd.Series([0.0]), r.reset_index(drop=True)]).cumsum()
    return {"n": len(r), "pf": profit_factor(r), "p10": pf_p10(r), "usd": r.sum() * usd_per_r,
            "avg": r.mean(), "win": (r > 0).mean() * 100, "dd": (equity.cummax() - equity).max() * usd_per_r}


def split_periods(tr, t0, t1, holdout):
    dev_end = t1 if holdout <= 0 else t0 + (t1 - t0) * (1.0 - holdout)
    mid = t0 + (dev_end - t0) / 2
    h1 = tr[tr["entree"] < mid] if not tr.empty else tr
    h2 = tr[(tr["entree"] >= mid) & (tr["entree"] < dev_end)] if not tr.empty else tr
    hold = tr[tr["entree"] >= dev_end] if (holdout > 0 and not tr.empty) else None
    return h1, h2, hold, mid, dev_end


def verdict(m1, m2):
    if m1["n"] < MIN_TRADES_PER_PERIOD or m2["n"] < MIN_TRADES_PER_PERIOD:
        return "ECHANTILLON INSUFFISANT"
    fails = [name for name, m in (("1re moitié", m1), ("2e moitié", m2)) if m["pf"] < TARGET_PF]
    if fails:
        return "NON : PF < objectif sur " + " et ".join(fails)
    robust = all(not np.isnan(m["p10"]) and m["p10"] >= 1.0 for m in (m1, m2))
    return "OBJECTIF ATTEINT (robuste)" if robust else "OBJECTIF ATTEINT (fragile : PF prudent < 1)"


def fmt_pf(x):
    return "  inf" if x == float("inf") else f"{x:5.2f}"


def fmt_p10(x):
    return "  n/a" if x != x else f"{x:5.2f}"


# ------------------------- PROGRAMME -----------------------------------------
def main():
    global TARGET_PF
    p = argparse.ArgumentParser(description="Backtest comparatif V5.0 / V5.1")
    p.add_argument("--source", choices=["MT5", "TWELVEDATA"], default=SOURCE)
    p.add_argument("--bars", type=int, default=BARS)
    p.add_argument("--api-key", default=None)
    p.add_argument("--csv", help="CSV local avec colonnes datetime,open,high,low,close")
    p.add_argument("--refresh", action="store_true", help="recharge les données au lieu d'utiliser le cache")
    p.add_argument("--spread", type=float, default=SPREAD)
    p.add_argument("--slippage", type=float, default=SLIPPAGE)
    p.add_argument("--target-pf", type=float, default=TARGET_PF)
    p.add_argument("--holdout", type=float, default=HOLDOUT, help="part finale réservée au contrôle (ex. 0.25)")
    p.add_argument("--lot", type=float)
    p.add_argument("--sl-usd", type=float)
    p.add_argument("--tp1-usd", type=float)
    p.add_argument("--tp2-usd", type=float)
    p.add_argument("--trades-out", default="comparatif_trades_v5_1.csv")
    p.add_argument("--summary-out", default="comparatif_variantes_v5_1.csv")
    p.add_argument("--bot", help="chemin du fichier xauusd_bot_ver_5_1.py")
    args = p.parse_args()

    TARGET_PF = args.target_pf
    bot = load_bot(args.bot)
    for name, value in (("LOT", args.lot), ("SL_USD", args.sl_usd), ("TP1_USD", args.tp1_usd), ("TP2_USD", args.tp2_usd)):
        if value is not None:
            setattr(bot, name, value)
    bot.refresh_ratios()

    raw = get_data(bot, args)
    if len(raw) < 2000:
        sys.exit("Pas assez de données pour un backtest comparatif (minimum 2000 bougies).")
    df = bot.add_indicators(raw.copy())
    t0, t1 = df["datetime"].iloc[0], df["datetime"].iloc[-1]
    usd_per_r = bot.SL_USD

    print(f"\n{len(VARIANTS)} variantes seront simulées sur {len(df)} bougies "
          f"({t0:%Y-%m-%d} -> {t1:%Y-%m-%d}). Cela peut prendre plusieurs minutes.")
    results, all_trades = [], []
    for name, overrides in VARIANTS:
        original = {k: getattr(bot, k) for k in overrides}
        for k, v in overrides.items():
            setattr(bot, k, v)
        bot.refresh_ratios()
        try:
            print(f"  -> {name} ...", flush=True)
            tr, blocked = run_backtest(bot, df, args.spread, args.slippage)
        finally:
            for k, v in original.items():
                setattr(bot, k, v)
            bot.refresh_ratios()
        h1, h2, hold, mid, dev_end = split_periods(tr, t0, t1, args.holdout)
        m_all, m1, m2 = metrics(tr, usd_per_r), metrics(h1, usd_per_r), metrics(h2, usd_per_r)
        m_hold = metrics(hold, usd_per_r) if hold is not None else None
        results.append({"name": name, "overrides": overrides, "all": m_all, "h1": m1, "h2": m2,
                        "hold": m_hold, "verdict": verdict(m1, m2), "blocked": blocked})
        if not tr.empty:
            all_trades.append(tr.assign(variante=name))

    # ----------------------------- RAPPORT -----------------------------------
    print("\n" + "=" * 128)
    print(f"COMPARATIF V5.0 / V5.1 | {t0:%Y-%m-%d} -> {t1:%Y-%m-%d} | {len(df)} bougies | "
          f"lot {bot.LOT} | SL {bot.SL_USD:g} $ | TP1 {bot.TP1_USD:g} $ | TP2 {bot.TP2_USD:g} $ | "
          f"coûts {args.spread + args.slippage:.2f} par trade")
    print(f"Objectif : PF net >= {TARGET_PF:g} sur CHAQUE période (>= {MIN_TRADES_PER_PERIOD} trades chacune). "
          f"Séparation des périodes au {mid:%Y-%m-%d}"
          + (f" ; contrôle final (holdout) à partir du {dev_end:%Y-%m-%d}." if args.holdout > 0 else "."))
    print("PF prudent (p10) = 10e percentile du PF sur 1000 tirages des trades ; < 1 = résultat fragile.")
    print("=" * 128)
    head = (f"{'Variante':<34} {'Trades':>6} {'PF tot':>6} | {'H1 n':>5} {'PF':>5} {'p10':>5} | "
            f"{'H2 n':>5} {'PF':>5} {'p10':>5} | {'Total $':>9} {'DD max $':>9} | Verdict")
    print(head)
    print("-" * len(head))
    for r in results:
        a, m1, m2 = r["all"], r["h1"], r["h2"]
        print(f"{r['name']:<34} {a['n']:>6} {fmt_pf(a['pf']):>6} | {m1['n']:>5} {fmt_pf(m1['pf'])} {fmt_p10(m1['p10'])} | "
              f"{m2['n']:>5} {fmt_pf(m2['pf'])} {fmt_p10(m2['p10'])} | {a['usd']:>+9.0f} {a['dd']:>9.0f} | {r['verdict']}")

    print("\nSignaux écartés par les filtres (par variante) :")
    for r in results:
        txt = ", ".join(f"{k} {v}" for k, v in sorted(r["blocked"].items(), key=lambda kv: -kv[1])) or "aucun"
        print(f"  {r['name']:<34} {txt}")

    winners = [r for r in results if r["verdict"].startswith("OBJECTIF ATTEINT")]
    print("\nVERDICT GLOBAL")
    if not winners:
        print(f"  - AUCUNE variante n'atteint PF >= {TARGET_PF:g} sur les deux périodes. V5.1 NON validée.")
        print("  - Ne forcez pas les paramètres jusqu'à ce que le chiffre apparaisse : ce serait de l'ajustement "
              "au passé, qui s'effondre en direct.")
        print("  - Pistes honnêtes : plus de données (BARS = 50000), un autre marché/période pour confirmer, "
              "ou accepter un objectif plus réaliste.")
    else:
        for w in winners:
            print(f"  - {w['name']} : {w['verdict']}")
            if w["overrides"]:
                print("    Réglages à copier en haut de xauusd_bot_ver_5_1.py : "
                      + " ; ".join(f"{k} = {v}" for k, v in w["overrides"].items()))
            if w["hold"] is not None:
                h = w["hold"]
                print(f"    Contrôle final (données jamais utilisées pour choisir) : {h['n']} trades, "
                      f"PF {fmt_pf(h['pf']).strip()}, total {h['usd']:+.0f} $"
                      + ("  -> CONFIRME l'objectif." if h["n"] >= 30 and h["pf"] >= TARGET_PF else
                         "  -> positif mais SOUS l'objectif." if h["n"] >= 30 and h["pf"] >= 1.0 else
                         "  -> NE TIENT PAS (ou moins de 30 trades : non concluant)."))
        if args.holdout <= 0:
            print(f"  - ATTENTION : {len(VARIANTS)} variantes ont été comparées sur les mêmes données ; une "
                  "variante peut réussir par chance. Relancez avec --holdout 0.25 et plus de données, puis "
                  "confirmez en démo avant tout passage en réel.")
    print("  - Le contrôle de la bougie en cours (CHECK_LIVE_CANDLE) n'est pas simulé : en direct, moins de trades.")
    print("=" * 128)

    summary = pd.DataFrame([{
        "variante": r["name"], "reglages": str(r["overrides"]), "trades": r["all"]["n"], "pf_total": r["all"]["pf"],
        "H1_trades": r["h1"]["n"], "H1_pf": r["h1"]["pf"], "H1_pf_p10": r["h1"]["p10"],
        "H2_trades": r["h2"]["n"], "H2_pf": r["h2"]["pf"], "H2_pf_p10": r["h2"]["p10"],
        "total_usd": round(r["all"]["usd"], 2), "dd_max_usd": round(r["all"]["dd"], 2), "verdict": r["verdict"],
    } for r in results])
    summary.to_csv(args.summary_out, index=False, sep=";", decimal=",", encoding="utf-8-sig")
    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(args.trades_out, index=False, sep=";", decimal=",",
                                                        encoding="utf-8-sig")
    print(f"Résumé enregistré dans {Path(args.summary_out).resolve()}")


if __name__ == "__main__":
    main()
