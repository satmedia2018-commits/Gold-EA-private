# -*- coding: utf-8 -*-
"""
Backtest XAUUSD M5 V5.0 (à placer avec xauusd_bot_ver_5_0.py)
============================================================================
Le script charge xauusd_bot_ver_5_0.py et rejoue les règles du bot sur l'historique OHLC :
  - indicateurs, signaux, filtres de bougies (doji, hammer, shooting star, couleur du signal) ;
  - LOT, SL, TP1 et TP2 fixes en dollars, tels que réglés dans xauusd_bot_ver_5_0.py ;
  - entrée à l'ouverture de la bougie M5 suivante, un seul trade à la fois ;
  - TP1 partiel puis stop au point d'entrée, TP2, stop, expiration (36 bougies) ;
  - si stop et objectif sont touchés dans la même bougie, le stop passe en premier (prudent) ;
  - coûts : spread + glissement déduits de chaque trade.

Il compare aussi les résultats SANS et AVEC les filtres de bougies, pour voir s'ils aident vraiment.

CE QUE LE BACKTEST NE REPRODUIT PAS
  - Le contrôle de la bougie qui vient de s'ouvrir (CHECK_LIVE_CANDLE) : il demande des prix tick par
    tick que les bougies M5 ne contiennent pas. En direct, le bot prendra donc MOINS de trades.
  - Les annonces économiques, les écarts de week-end et le glissement réel.
Un backtest ne prédit pas l'avenir : ne bricolez pas les paramètres jusqu'à ce que le passé "colle".

UTILISATION (Thonny) : réglez les constantes ci-dessous, puis lancez le fichier (Run).
En ligne de commande : python backtest_xauusd.py --bars 30000 --spread 0.30
"""

import argparse
import importlib.util
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

# ------------------------- RÉGLAGES (modifiables) ----------------------------
SOURCE = "MT5"             # "MT5" (terminal ouvert, mêmes prix qu'Exness) ou "TWELVEDATA"
BARS = 50000               # 50 000 bougies M5 représentent environ 174 jours de cotation continue
API_KEY = os.environ.get("TWELVEDATA_API_KEY", "")  # aucune clé secrète dans le code
SPREAD = 0.30              # spread moyen en dollars (points de prix) : ajustez à votre compte
SLIPPAGE = 0.10            # glissement moyen par trade en dollars
COMPARE = True             # compare avec et sans filtres de bougies
TRADES_FILE = Path("backtest_trades_v5_0.csv")
TD_API_URL = "https://api.twelvedata.com/time_series"


# ------------------------- CHARGEMENT DE LA STRATÉGIE ------------------------
def load_bot(path=None):
    here = Path(__file__).resolve().parent
    candidates = [Path(path)] if path else [here / "xauusd_bot_ver_5_0.py", here / "xauusd_bot.py", here / "XAUUSD BOT.py", here / "XauUSD bot.py"]
    for p in candidates:
        if p.exists():
            spec = importlib.util.spec_from_file_location("bot", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["bot"] = mod
            spec.loader.exec_module(mod)
            print(f"Stratégie chargée depuis : {p.name}")
            return mod
    sys.exit("Fichier du bot introuvable : placez ce script dans le même dossier que 'xauusd_bot.py' "
             "ou utilisez --bot.")


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
    dropped = before - len(df)
    if dropped:
        print(f"Nettoyage des données : {dropped} ligne(s) vide(s)/doublon(s) supprimée(s).")
    if len(df) > 1 and not df["datetime"].is_monotonic_increasing:
        raise ValueError("Les dates ne sont pas triées chronologiquement.")
    return df


def download_mt5(bot, n_bars):
    """Historique M5 lu directement dans MT5 (heure du serveur Exness, mêmes prix que le bot)."""
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
        print(f"Seulement {len(df)} bougies disponibles dans MT5 (demandé : {n_bars}). "
              f"Pour plus d'historique, faites défiler le graphique M5 vers la gauche.")
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
        # La réponse est demandée en DESC : la dernière ligne est la plus ancienne après tri API.
        oldest = pd.to_datetime(df["datetime"].iloc[-1], utc=True)
        end_date = (oldest - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(8)                                    # limite du plan gratuit
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
def run_backtest(bot, raw_df, spread, slippage, tp1_frac, use_filters=True):
    """Simulation séquentielle M5. Chaque bougie future n'est traitée qu'une fois par trade.

    L'entrée est approximée par l'open de la bougie suivant le signal. CHECK_LIVE_CANDLE est exclu faute de ticks.
    Hypothèse OHLC prudente : stop prioritaire si stop/cible sont touchés ensemble ; TP1 puis retour au BE
    visibles dans une même bougie sont comptés comme BE. Les ticks, spread variable et gaps exacts
    ne sont pas reconstruits par ce moteur.
    """
    df = bot.add_indicators(raw_df.copy())
    n = len(df)
    i = bot.EMA_SLOW + 10
    sign_of = {"VENTE": -1, "ACHAT": 1}
    cost_pts = max(0.0, float(spread)) + max(0.0, float(slippage))
    trades, blocked = [], Counter()

    original_filter = bot.candle_filter_reason
    if not use_filters:
        bot.candle_filter_reason = lambda d, side: ""
    try:
        while i < n - 1:
            if i % 5000 == 0:
                print(f"    ... {i}/{n} bougies", flush=True)
            sig, _ = bot.detect_signal(df.iloc[:i + 1])
            if sig is None:
                if use_filters and bot.LAST_BLOCK:
                    reason = bot.LAST_BLOCK
                    key = ("couleur du signal" if "bougie du signal" in reason else
                           "doji" if "DOJI" in reason else "hammer" if "HAMMER" in reason else
                           "shooting star" if "SHOOTING" in reason else "autre")
                    blocked[key] += 1
                i += 1
                continue

            # Le bot live envoie l'ordre après le signal, sur la bougie qui vient de s'ouvrir.
            # En OHLC, on approxime ce prix par l'open de i+1 (pas par le close du signal).
            next_open = float(df.iloc[i + 1]["open"])
            sig = bot.make_signal(sig.time, sig.side, sig.setup, next_open)
            future = df.iloc[i + 1:i + 1 + bot.MAX_BARS_ACTIVE]
            events, finished = bot.manage_active(sig, future)
            if not finished:
                # Trade encore ouvert à la fin de l'historique : non comptabilisé dans les résultats fermés.
                break
            if not events:
                i += 1
                continue

            # Parcours simulé jusqu'à la sortie : excursions MFE/MAE sans regarder après le trade.
            path_used = future.iloc[:sig.bars]
            if path_used.empty:
                i += 1
                continue
            if sig.side == "ACHAT":
                mfe_r = max(0.0, (float(path_used["high"].max()) - sig.entry) / sig.risk)
                mae_r = max(0.0, (sig.entry - float(path_used["low"].min())) / sig.risk)
            else:
                mfe_r = max(0.0, (sig.entry - float(path_used["low"].min())) / sig.risk)
                mae_r = max(0.0, (float(path_used["high"].max()) - sig.entry) / sig.risk)

            kinds = [kind for _, kind in events]
            final = kinds[-1]
            exit_idx = min(i + sig.bars, n - 1)
            if final == "STOP":
                r = -1.0
            elif final == "BREAKEVEN":
                r = tp1_frac * bot.TP1_R
            elif final == "TP2":
                r = tp1_frac * bot.TP1_R + (1.0 - tp1_frac) * bot.TP2_R
            else:
                move = sign_of[sig.side] * (float(df.iloc[exit_idx]["close"]) - sig.entry) / sig.risk
                r = tp1_frac * bot.TP1_R + (1.0 - tp1_frac) * move if "TP1" in kinds else move

            r_net = r - cost_pts / sig.risk
            trades.append({
                "signal_time": df.iloc[i]["datetime"],
                "entree": df.iloc[i + 1]["datetime"], "sortie": df.iloc[exit_idx]["datetime"],
                "sens": sig.side, "setup": sig.setup, "entry": round(sig.entry, 2),
                "bougies": sig.bars, "MFE_R": round(mfe_r, 4), "MAE_R": round(mae_r, 4),
                "sortie_type": final,
                "tp1_fraction_reelle": round(tp1_frac, 4),
                "r_brut": round(r, 6), "cout_R": round(cost_pts / sig.risk, 6),
                "r_net": round(r_net, 6),
                "profit_usd_net": round(r_net * bot.SL_USD, 2),
            })
            # Comme le bot live, une nouvelle décision est possible à la clôture de la bougie de sortie.
            i = exit_idx
    finally:
        bot.candle_filter_reason = original_filter
    return pd.DataFrame(trades), blocked


# ------------------------- STATISTIQUES --------------------------------------
def stats(r, usd_per_r):
    n = len(r)
    wins, losses = r[r > 0], r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    equity = pd.concat([pd.Series([0.0]), r.reset_index(drop=True)]).cumsum()
    streak = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        streak = max(streak, cur)
    return {"n": n, "win": len(wins) / n * 100, "avg": r.mean(), "total": r.sum(), "pf": pf,
            "dd": (equity.cummax() - equity).max(), "streak": streak,
            "usd": r.sum() * usd_per_r, "dd_usd": (equity.cummax() - equity).max() * usd_per_r}


def line(label, r, usd_per_r):
    if len(r) == 0:
        return f"  {label:<34} aucun trade"
    s = stats(r, usd_per_r)
    return (f"  {label:<34} {s['n']:>4} trades | gagnants {s['win']:>5.1f}% | moy {s['avg']:>+6.2f}R "
            f"| total {s['usd']:>+9.0f} $ | PF {s['pf']:>4.2f} | DD max {s['dd_usd']:>7.0f} $")


def session_of(hour):
    if hour < 7:
        return "Asie (00-07h)"
    if hour < 13:
        return "Londres (07-13h)"
    if hour < 21:
        return "New York (13-21h)"
    return "Nuit (21-24h)"


def report(tr, blocked, tr_nofilter, df, bot, spread, slippage):
    usd = bot.SL_USD
    print("\n" + "=" * 86)
    print(f"BACKTEST XAUUSD M5 | {df['datetime'].iloc[0]:%Y-%m-%d} -> {df['datetime'].iloc[-1]:%Y-%m-%d} "
          f"| {len(df)} bougies")
    print(f"Lot {bot.LOT} | SL {bot.SL_USD:g} $ ({bot.usd_to_points(bot.SL_USD):.1f} distance prix) | "
          f"TP1 {bot.TP1_USD:g} $ | TP2 {bot.TP2_USD:g} $ | fraction TP1 réellement simulée : {bot.tp1_fraction():.1%} | "
          f"coûts simplifiés : spread {spread:.2f} + glissement {slippage:.2f}")
    print(f"Filtres stratégie : New York {'ACTIVÉE' if bot.ENABLE_NEW_YORK_SESSION else 'DÉSACTIVÉE'} "
          f"({bot.NEW_YORK_START_UTC:02d}:00-{bot.NEW_YORK_END_UTC:02d}:00 UTC) | "
          f"Rebond EMA20 ACHAT {'ACTIVÉ' if bot.ENABLE_BUY_EMA20_PULLBACK else 'DÉSACTIVÉ'}")
    print("Hypothèses : entrée à l’open suivante ; stop prioritaire si stop/cible dans la même bougie ; "
          "TP1 puis retour BE dans une même bougie comptés prudemment comme BE ; "
          "pas de ticks, spread variable, gaps exacts ni commissions historiques.")
    print("=" * 86)
    if tr.empty:
        print("Aucun trade généré sur cette période.")
        return

    print("\nRésultat global (avec les filtres du bot)")
    print(line("Brut (sans coûts)", tr["r_brut"], usd))
    print(line("NET (après coûts)", tr["r_net"], usd))
    s = stats(tr["r_net"], usd)
    print(f"  Plus longue série de pertes : {s['streak']} trades | durée moyenne : {tr['bougies'].mean():.0f} bougies")

    if tr_nofilter is not None and not tr_nofilter.empty:
        print("\nLes filtres de bougies aident-ils ? (résultat NET)")
        print(line("SANS filtres de bougies", tr_nofilter["r_net"], usd))
        print(line("AVEC filtres (comme le bot)", tr["r_net"], usd))
    print("\nSignaux écartés par les filtres : " +
          (", ".join(f"{k} {v}" for k, v in blocked.most_common()) if blocked else "aucun") +
          "  (chaque signal peut être compté sur plusieurs bougies consécutives)")

    print("\nPar sens")
    for side, g in tr.groupby("sens"):
        print(line(side, g["r_net"], usd))
    print("\nPar type de signal")
    for setup, g in tr.groupby("setup"):
        print(line(setup[:34], g["r_net"], usd))
    print("\nPar session (heure UTC des données)")
    tr = tr.assign(session=tr["entree"].dt.hour.map(session_of))
    for sess, g in tr.groupby("session"):
        print(line(sess, g["r_net"], usd))
    print("\nTypes de sortie : " + ", ".join(f"{k} {v}" for k, v in tr["sortie_type"].value_counts().items()))
    if {"MFE_R", "MAE_R"}.issubset(tr.columns):
        print(f"\nExcursions prix : MFE moyen {tr['MFE_R'].mean():.2f}R | MAE moyen {tr['MAE_R'].mean():.2f}R")

    half = len(tr) // 2
    first, second = tr["r_net"].iloc[:half], tr["r_net"].iloc[half:]
    print("\nContrôle de stabilité (première moitié vs seconde moitié)")
    print(line("1ère moitié", first, usd))
    print(line("2ème moitié", second, usd))

    print("\nVerdict")
    if len(tr) < 100:
        print(f"  - Seulement {len(tr)} trades : échantillon trop petit pour conclure. Allongez la période.")
    avg = tr["r_net"].mean()
    if avg <= 0:
        print("  - Espérance NÉGATIVE après coûts : sur cette période, la stratégie perd de l'argent. "
              "Ne la passez pas en réel.")
    else:
        print(f"  - Espérance positive après coûts ({avg:+.2f}R, soit {avg * usd:+.1f} $ par trade) sur cette "
              "période : cela ne garantit rien pour l'avenir.")
    if len(first) and len(second) and (first.mean() > 0) != (second.mean() > 0):
        print("  - Les deux moitiés ne vont pas dans le même sens : résultat instable, probablement du hasard.")
    if tr["r_brut"].mean() > 0 >= avg:
        print("  - Gagnante avant coûts mais perdante après : le spread et le glissement mangent l'avantage.")
    if tr_nofilter is not None and not tr_nofilter.empty and tr_nofilter["r_net"].sum() > tr["r_net"].sum():
        print("  - Sans filtres de bougies, le total est meilleur : sur cette période, les filtres n'ont pas aidé.")
    tp1_frac = bot.tp1_fraction()
    avg_win_if_tp2 = tp1_frac * bot.TP1_R + (1.0 - tp1_frac) * bot.TP2_R
    be = 100.0 / (1.0 + avg_win_if_tp2) if avg_win_if_tp2 > 0 else float("inf")
    print(f"  - Seuil théorique de réussite si chaque gagnant atteint TP2 : {be:.1f}% avant coûts ; "
          "ce seuil ne remplace pas l'espérance réellement mesurée.")
    print("  - Le filtre CHECK_LIVE_CANDLE n'est pas simulé : il nécessite le tick de la nouvelle bougie.")
    print("=" * 86)


# ------------------------- PROGRAMME -----------------------------------------
def main():
    p = argparse.ArgumentParser(description="Backtest du bot XAUUSD M5")
    p.add_argument("--source", choices=["MT5", "TWELVEDATA"], default=SOURCE)
    p.add_argument("--bars", type=int, default=BARS)
    p.add_argument("--api-key", default=None)
    p.add_argument("--csv", help="CSV local avec colonnes datetime,open,high,low,close")
    p.add_argument("--refresh", action="store_true", help="recharge les données au lieu d'utiliser le cache")
    p.add_argument("--spread", type=float, default=SPREAD)
    p.add_argument("--slippage", type=float, default=SLIPPAGE)
    p.add_argument("--tp1-fraction", type=float, default=None, help="par défaut : valeur du bot")
    p.add_argument("--lot", type=float, help="remplace LOT du bot")
    p.add_argument("--sl-usd", type=float, help="remplace SL_USD du bot")
    p.add_argument("--tp1-usd", type=float, help="remplace TP1_USD du bot")
    p.add_argument("--tp2-usd", type=float, help="remplace TP2_USD du bot")
    p.add_argument("--no-compare", action="store_true", help="ne pas comparer avec/sans filtres")
    p.add_argument("--trades-out", default=str(TRADES_FILE), help="fichier CSV de sortie des trades")
    p.add_argument("--bot", help="chemin du fichier xauusd_bot.py")
    args = p.parse_args()

    bot = load_bot(args.bot)
    for name, value in (("LOT", args.lot), ("SL_USD", args.sl_usd),
                        ("TP1_USD", args.tp1_usd), ("TP2_USD", args.tp2_usd)):
        if value is not None:
            setattr(bot, name, value)
    bot.refresh_ratios()
    tp1_frac = args.tp1_fraction if args.tp1_fraction is not None else bot.tp1_fraction()

    df = get_data(bot, args)
    if len(df) < 500:
        sys.exit("Pas assez de données pour un backtest.")

    print("Simulation AVEC les filtres du bot...")
    trades, blocked = run_backtest(bot, df, args.spread, args.slippage, tp1_frac, use_filters=True)
    trades_nofilter = None
    if COMPARE and not args.no_compare:
        print("Simulation SANS filtres de bougies (pour comparer)...")
        trades_nofilter, _ = run_backtest(bot, df, args.spread, args.slippage, tp1_frac, use_filters=False)

    report(trades, blocked, trades_nofilter, df, bot, args.spread, args.slippage)
    if not trades.empty:
        out = Path(args.trades_out)
        trades.to_csv(out, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        print(f"Détail des trades enregistré dans {out.resolve()}")


if __name__ == "__main__":
    main()
