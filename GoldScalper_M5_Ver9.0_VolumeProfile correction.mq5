//+------------------------------------------------------------------+
//|                                      GoldScalper_M5_v9_Robust.mq5 |
//|  EA XAUUSD M5 : routeur de régime (ADX / ATR / EMA)              |
//|  v9.00 : lots/spread/VP corriges + compteurs de diagnostic       |
//+------------------------------------------------------------------+
#property copyright "GoldScalper M5 v9.00 Robust"
#property version   "9.00"
#property strict

#include <Trade\Trade.mqh>

#define PANEL_W     300
#define ROW_H       14
#define HEAD_H      30

#define COL_GREEN   C'38,166,91'
#define COL_RED     C'214,69,65'
#define COL_BLUE    C'66,165,245'
#define COL_AMBER   C'255,167,38'
#define COL_LABEL   C'140,150,168'
#define COL_ACCENT  C'255,193,7'

//--- compteurs de diagnostic (Journal : "pourquoi pas de trade ?")
#define R_SESSION 0
#define R_SPREAD  1
#define R_NEWS    2
#define R_DAYLOCK 3
#define R_MAXDAY  4
#define R_PAUSE   5
#define R_INPOS   6
#define R_ATR     7
#define R_DATA    8
#define R_NOSIG   9
#define R_STOPS   10
#define R_NOLOT   11
#define R_FAIL    12
#define R_OPENED  13
#define R_SIGA    14
#define R_SIGB    15
#define R_SIGC    16
#define R_SIGD    17
#define R_N       18

string g_rn[R_N] =
  {
   "Hors session / week-end", "Spread trop eleve", "Fenetre news USD", "Perte du jour atteinte",
   "Max trades/jour atteint", "Pause serie de pertes", "Position deja ouverte",
   "ATR hors plage", "Donnees indicateurs", "Aucun signal",
   "Stops trop proches", "Lot impossible (risque/marge)", "Ordre refuse",
   "TRADES OUVERTS", "Signaux A (breakout)", "Signaux B (pullback)",
   "Signaux C (retour moyenne)", "Signaux D (volume profile)"
  };
long g_cnt[R_N];

//--- Paramètres généraux
input group "=== Général ==="
input long   InpMagic           = 20261020;
input string InpComment         = "GoldM5";
input int    InpBrokerGMTOffset = 0;      // Decalage heure serveur vs GMT (Exness = 0, A VERIFIER)
input int    InpSlippagePoints  = 100;    // 100 points = 0.10$ sur l'or (3 decimales)

input group "=== Risque ==="
input double InpRiskPercent     = 1.0;     // % du solde risque par trade
input double InpMaxDailyLossPct = 4.0;
input int    InpMaxTradesPerDay = 12;
input int    InpMaxConsecLosses = 3;
input int    InpLossPauseBars   = 6;
input bool   InpAllowMinLot     = true;    // lot mini si le calcul donne moins (petit compte)
input double InpMinLotRiskMult  = 2.0;     // ...seulement si risque reel <= X * risque cible
input double InpMaxLots         = 5.0;

input group "=== Sessions (heures GMT) ==="
input int    InpAsiaStart       = 0;
input int    InpAsiaEnd         = 7;
input int    InpLondonStart     = 7;
input int    InpLondonEnd       = 12;
input int    InpNYStart         = 12;
input int    InpNYEnd           = 20;
input bool   InpTradeAsia       = true;
input int    InpFridayCloseGMT  = 20;      // Vendredi : plus d'entree + fermeture apres cette heure

input group "=== Filtres ==="
input double InpMaxSpread       = 0.60;    // Spread max en $ (ask-bid)
input double InpMaxSpreadATR    = 0.15;    // Spread max en fraction de l'ATR
input int    InpEntryWindowSec  = 45;      // Delai max apres ouverture de barre (retente si spread haut)
input double InpATRMinPct       = 0.020;   // ATR mini en % du prix (0.02% = 0.80$ a 4000)
input double InpATRMaxPct       = 0.350;   // ATR maxi en % du prix
input bool   InpUseNewsFilter   = true;
input int    InpNewsBefore      = 20;
input int    InpNewsAfter       = 20;

input group "=== Indicateurs ==="
input int    InpATRPeriod       = 14;
input int    InpADXPeriod       = 14;
input int    InpEMAFast         = 20;
input int    InpEMASlow         = 50;
input double InpADXTrend        = 20.0;
input double InpADXRange        = 20.0;

input group "=== Filtre de tendance supérieure / qualité ==="
input bool   InpUseHTFTrend       = true;
input ENUM_TIMEFRAMES InpTrendTF  = PERIOD_M15;
input int    InpHTFFastEMA        = 20;
input int    InpHTFSlowEMA        = 50;
input bool   InpRequireADXRising  = false;
input double InpB_MinBodyRatio    = 0.35;
input double InpB_MaxExtensionATR = 0.90;

input group "=== Module A : Breakout ==="
input bool   InpEnableA         = true;
input double InpA_RiskMult      = 1.0;
input double InpA_SL_ATR        = 1.5;
input double InpA_RR            = 1.3;
input double InpA_BufferATR     = 0.10;
input double InpA_MaxChaseATR   = 1.0;

input group "=== Module B : Pullback ==="
input bool   InpEnableB         = true;
input double InpB_RiskMult      = 1.0;
input int    InpB_Lookback      = 5;
input double InpB_RR            = 1.8;
input double InpB_SLMinATR      = 0.8;
input double InpB_SLMaxATR      = 2.0;
input double InpB_TouchATR      = 0.25;

input group "=== Module C : Retour à la moyenne ==="
input bool   InpEnableC         = true;
input double InpC_RiskMult      = 0.5;
input double InpC_DevATR        = 1.6;
input double InpC_SL_ATR        = 1.2;
input double InpC_MinRR         = 1.0;

input group "=== Module D : Volume Profile ==="
input bool   InpEnableD         = false;   // D a perdu dans le backtest v5.3 : a tester seul avant de l'activer
input double InpD_RiskMult      = 1.0;
input int    InpVPBars          = 288;
input int    InpVPBins          = 80;
input double InpVPValueArea     = 70.0;
input double InpVPHVNFactor     = 1.15;
input double InpVPLVNFactor     = 0.65;
input int    InpVPMaxNodes      = 1;
input bool   InpD_NeedADX       = true;
input double InpD_TouchATR      = 0.35;
input double InpD_SLBufferATR   = 0.30;
input double InpD_SLMinATR      = 0.60;
input double InpD_SLMaxATR      = 3.00;
input double InpD_MinRR         = 1.10;
input double InpD_DefaultRR     = 1.50;
input bool   InpD_UseVPStops    = true;

input group "=== SL / TP fixes ==="
input bool   InpUseFixedStops    = false;
input double InpFixedSL         = 4.0;
input double InpFixedTP         = 6.0;

input group "=== Gestion de position ==="
input double InpBE_R            = 1.0;
input double InpBE_Offset_R     = 0.15;
input double InpTrailStart_R    = 1.5;     // Le trailing ne demarre qu'a +1.5R
input double InpTrailATR        = 1.0;
input int    InpMaxBars         = 36;

input group "=== Affichage ==="
input bool   InpShowPanel       = true;
input int    InpPanelX          = 10;
input int    InpPanelY          = 20;
input int    InpLastTrades      = 3;
input bool   InpShowArrows      = true;
input bool   InpShowEMA         = true;
input int    InpEMABars         = 120;
input bool   InpShowAsia        = true;
input bool   InpShowSR          = true;
input int    InpSRBars          = 48;
input bool   InpShowSubwindows  = false;
input bool   InpApplyTheme      = true;
input bool   InpColorCandles    = true;
input color  InpColCandleBull   = C'0,200,83';
input color  InpColCandleBear   = C'255,23,68';
input bool   InpClearArrowsExit = false;
input color  InpColBuy          = C'0,200,83';
input color  InpColSell         = C'255,23,68';
input color  InpColEMAFast      = C'255,193,7';
input color  InpColEMASlow      = C'66,165,245';
input color  InpColAsia         = C'0,150,136';
input color  InpSupportColor    = C'0,200,83';
input color  InpResistColor     = C'160,32,240';
input int    InpSRLineWidth     = 3;
input bool   InpShowVP          = true;
input color  InpColVA           = clrOrange;
input int    InpVAWidth         = 2;
input color  InpColVP           = clrWhite;
input int    InpNodeWidth       = 2;
input int    InpDashBars        = 3;
input int    InpGapBars         = 2;

//--- Structures et globales
struct SSignal
  {
   int    dir;
   double slDist;
   double tpDist;
   int    module;
   double riskMult;
   double atr;
  };

CTrade   trade;
int      hATR = INVALID_HANDLE, hADX = INVALID_HANDLE;
int      hEMAF = INVALID_HANDLE, hEMAS = INVALID_HANDLE;
int      hHTFF = INVALID_HANDLE, hHTFS = INVALID_HANDLE;

datetime g_lastBar   = 0;
datetime g_dayStart  = 0;
double   g_dayStartEquity = 0.0;
bool     g_asiaValid = false;
double   g_asiaHigh  = 0, g_asiaLow = 0;
bool     g_breakDone = false;

double   g_dailyPnL     = 0;
int      g_tradesToday  = 0;
int      g_consecLosses = 0;

double   g_initRisk  = 0;
int      g_posModule = 0;
bool     g_hadPos    = false;

datetime g_lastExitTime = 0;
datetime g_newsCheck = 0;
bool     g_newsBlock = false;
string   g_lastStatus = "";
bool     g_evalDone = true;
bool     g_spreadBlocked = false;
int      g_whyCode = -1;

bool     g_draw       = true;
int      g_px = 10, g_py = 20, g_row = 0;
ulong    g_lastPanel  = 0, g_lastStat = 0;
bool     g_forcePanel = false, g_forceStats = false;
int      g_arrowN     = 0;
int      g_adxWin = -1, g_atrWin = -1;
string   g_adxName = "", g_atrName = "";

double   g_sup = 0, g_res = 0;
datetime g_srT1 = 0;

bool     g_vpValid = false;
datetime g_vpBar   = 0;
datetime g_vpT1    = 0;
double   g_poc = 0, g_vah = 0, g_val = 0, g_vpStep = 0;
double   g_hvn[];
double   g_lvn[];

double   g_adx = 0, g_pdi = 0, g_mdi = 0, g_atrV = 0, g_atr4 = 0;
double   g_emaF = 0, g_emaS = 0, g_close1 = 0;

ulong    g_pid[];
int      g_pmod[];
double   g_pcom[];
int      g_statDeals = 0;
int      g_stTrades[5];
int      g_stWins[5];
double   g_stNet[5];
double   g_grossP = 0, g_grossL = 0, g_cum = 0, g_peak = 0, g_maxDD = 0;

double   g_ltPnl[5];
int      g_ltDir[5];
int      g_ltMod[5];
datetime g_ltTime[5];
int      g_ltCount = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(_Period != PERIOD_M5)
      Print("WARNING: this EA is designed for the M5 timeframe");
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("WARNING: this EA is designed for gold (XAUUSD)");

   hATR  = iATR(_Symbol, _Period, InpATRPeriod);
   hADX  = iADX(_Symbol, _Period, InpADXPeriod);
   hEMAF = iMA(_Symbol, _Period, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMAS = iMA(_Symbol, _Period, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   hHTFF = iMA(_Symbol, InpTrendTF, InpHTFFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   hHTFS = iMA(_Symbol, InpTrendTF, InpHTFSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(hATR == INVALID_HANDLE || hADX == INVALID_HANDLE || hEMAF == INVALID_HANDLE ||
      hEMAS == INVALID_HANDLE || hHTFF == INVALID_HANDLE || hHTFS == INVALID_HANDLE)
     {
      Print("Indicator creation failed");
      return INIT_FAILED;
     }

   trade.SetExpertMagicNumber((ulong)InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   g_draw = !(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE));

   ArrayInitialize(g_cnt, 0);
   ResetStats();
   UpdateDay();

   if(g_draw)
     {
      if(InpApplyTheme) ApplyTheme();
      if(InpColorCandles) ApplyCandleColors();
      ObjectsDeleteAll(0, "GSS_");
      ObjectsDeleteAll(0, "GSR_");
      ObjectsDeleteAll(0, "GSL_");
      ObjectsDeleteAll(0, "GSP_");
      ObjectsDeleteAll(0, "GSV_");
      ChartSetInteger(0, CHART_SHIFT, true);
      ChartSetDouble(0, CHART_SHIFT_SIZE, 12.0);
      if(InpShowPanel) PanelInit();
      AddChartIndicators();
      EventSetTimer(1);
      RefreshVisuals(true);
     }
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   string rpt = "=== RESUME DIAGNOSTIC GoldScalper v9 (barres bloquees par cause) ===\n";
   for(int i = 0; i < R_N; i++)
      rpt += "  " + g_rn[i] + " : " + IntegerToString((int)g_cnt[i]) + "\n";
   Print(rpt);
   if(g_draw)
     {
      if(g_atrName != "") ChartIndicatorDelete(0, g_atrWin, g_atrName);
      if(g_adxName != "") ChartIndicatorDelete(0, g_adxWin, g_adxName);
      ObjectsDeleteAll(0, "GSP_");
      ObjectsDeleteAll(0, "GSL_");
      ObjectsDeleteAll(0, "GSR_");
      ObjectsDeleteAll(0, "GSS_");
      ObjectsDeleteAll(0, "GSV_");
      if(InpClearArrowsExit) ObjectsDeleteAll(0, "GSA_");
      ChartRedraw(0);
     }
   if(hATR  != INVALID_HANDLE) IndicatorRelease(hATR);
   if(hADX  != INVALID_HANDLE) IndicatorRelease(hADX);
   if(hEMAF != INVALID_HANDLE) IndicatorRelease(hEMAF);
   if(hEMAS != INVALID_HANDLE) IndicatorRelease(hEMAS);
   if(hHTFF != INVALID_HANDLE) IndicatorRelease(hHTFF);
   if(hHTFS != INVALID_HANDLE) IndicatorRelease(hHTFS);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ManagePosition();
   datetime bt = iTime(_Symbol, _Period, 0);
   if(bt != g_lastBar)
     {
      g_lastBar = bt;
      OnNewBar();
      RefreshVisuals(true);
     }
   else
      RefreshVisuals(false);

   if(!g_evalDone)
      TryEntry(bt);
  }

//+------------------------------------------------------------------+
void OnTimer() { RefreshVisuals(false); }

//+------------------------------------------------------------------+
int GetGMTHour(datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   int h = (dt.hour - InpBrokerGMTOffset) % 24;
   if(h < 0) h += 24;
   return h;
  }

//+------------------------------------------------------------------+
bool FindPosition(ulong &ticket)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      ticket = t;
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
void UpdateDay()
  {
   datetime ds = iTime(_Symbol, PERIOD_D1, 0);
   if(ds != g_dayStart)
     {
      g_dayStart  = ds;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_asiaValid = false;
      g_breakDone = false;
     }

   if(g_asiaValid) return;

   datetime s = g_dayStart + (InpAsiaStart + InpBrokerGMTOffset) * 3600;
   datetime e = g_dayStart + (InpAsiaEnd   + InpBrokerGMTOffset) * 3600;
   if(TimeCurrent() < e) return;

   MqlRates ar[];
   int n = CopyRates(_Symbol, PERIOD_M5, s, e - 1, ar);
   if(n < 12) return;

   double hi = ar[0].high, lo = ar[0].low;
   for(int i = 1; i < n; i++)
     {
      if(ar[i].high > hi) hi = ar[i].high;
      if(ar[i].low  < lo) lo = ar[i].low;
     }
   g_asiaHigh  = hi;
   g_asiaLow   = lo;
   g_asiaValid = true;
  }

//+------------------------------------------------------------------+
void UpdateDailyStats()
  {
   if(g_dayStart == 0) g_dayStart = iTime(_Symbol, PERIOD_D1, 0);
   g_dailyPnL = 0; g_tradesToday = 0; g_consecLosses = 0; g_lastExitTime = 0;
   if(!HistorySelect(g_dayStart, TimeCurrent() + 60)) return;

   int total = HistoryDealsTotal();
   bool streakOpen = true;
   for(int i = total - 1; i >= 0; i--)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic) continue;

      long entry = HistoryDealGetInteger(tk, DEAL_ENTRY);
      if(entry == DEAL_ENTRY_IN)
        {
         g_tradesToday++;
         g_dailyPnL += HistoryDealGetDouble(tk, DEAL_COMMISSION);
         continue;
        }
      if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_INOUT || entry == DEAL_ENTRY_OUT_BY)
        {
         double p = HistoryDealGetDouble(tk, DEAL_PROFIT)
                    + HistoryDealGetDouble(tk, DEAL_COMMISSION)
                    + HistoryDealGetDouble(tk, DEAL_SWAP);
         g_dailyPnL += p;
         if(g_lastExitTime == 0)
            g_lastExitTime = (datetime)HistoryDealGetInteger(tk, DEAL_TIME);
         if(streakOpen)
           {
            if(p < 0) g_consecLosses++;
            else      streakOpen = false;
           }
        }
     }
  }

//+------------------------------------------------------------------+
void ResetStats()
  {
   ArrayResize(g_pid, 0);
   ArrayResize(g_pmod, 0);
   ArrayResize(g_pcom, 0);
   g_statDeals = 0;
   ArrayInitialize(g_stTrades, 0);
   ArrayInitialize(g_stWins, 0);
   ArrayInitialize(g_stNet, 0.0);
   ArrayInitialize(g_ltPnl, 0.0);
   ArrayInitialize(g_ltDir, 0);
   ArrayInitialize(g_ltMod, 0);
   ArrayInitialize(g_ltTime, 0);
   g_ltCount = 0;
   g_grossP = 0; g_grossL = 0; g_cum = 0; g_peak = 0; g_maxDD = 0;
  }

void StatsAddCash(double v)
  {
   g_cum += v;
   if(g_cum > g_peak) g_peak = g_cum;
   double dd = g_peak - g_cum;
   if(dd > g_maxDD) g_maxDD = dd;
  }

void UpdateGlobalStats()
  {
   if(!HistorySelect(0, TimeCurrent() + 60)) return;
   int total = HistoryDealsTotal();
   if(total < g_statDeals) ResetStats();

   for(int i = g_statDeals; i < total; i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic) continue;

      long  entry = HistoryDealGetInteger(tk, DEAL_ENTRY);
      ulong pid   = (ulong)HistoryDealGetInteger(tk, DEAL_POSITION_ID);

      if(entry == DEAL_ENTRY_IN)
        {
         string cm = HistoryDealGetString(tk, DEAL_COMMENT);
         int m = 0, L = StringLen(cm);
         if(L > 0)
           {
            string c = StringSubstr(cm, L - 1, 1);
            if(c == "A")      m = 1;
            else if(c == "B") m = 2;
            else if(c == "C") m = 3;
            else if(c == "D") m = 4;
           }
         double com = HistoryDealGetDouble(tk, DEAL_COMMISSION);
         int n = ArraySize(g_pid);
         ArrayResize(g_pid, n + 1);
         ArrayResize(g_pmod, n + 1);
         ArrayResize(g_pcom, n + 1);
         g_pid[n]  = pid;
         g_pmod[n] = m;
         g_pcom[n] = com;

         g_stNet[m] += com;
         if(com < 0) g_grossL += -com;
         StatsAddCash(com);
         continue;
        }

      if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_INOUT || entry == DEAL_ENTRY_OUT_BY)
        {
         double p = HistoryDealGetDouble(tk, DEAL_PROFIT)
                    + HistoryDealGetDouble(tk, DEAL_COMMISSION)
                    + HistoryDealGetDouble(tk, DEAL_SWAP);
         int m = 0;
         double ecom = 0;
         for(int k = ArraySize(g_pid) - 1; k >= 0; k--)
            if(g_pid[k] == pid)
              {
               m = g_pmod[k];
               ecom = g_pcom[k];
               break;
              }
         g_stTrades[m]++;
         if(p > 0) { g_stWins[m]++; g_grossP += p; }
         else       g_grossL += -p;
         g_stNet[m] += p;
         StatsAddCash(p);

         long dtp = HistoryDealGetInteger(tk, DEAL_TYPE);
         for(int q = 4; q > 0; q--)
           {
            g_ltPnl[q]  = g_ltPnl[q - 1];
            g_ltDir[q]  = g_ltDir[q - 1];
            g_ltMod[q]  = g_ltMod[q - 1];
            g_ltTime[q] = g_ltTime[q - 1];
           }
         g_ltPnl[0]  = p + ecom;
         g_ltDir[0]  = (dtp == DEAL_TYPE_SELL) ? 1 : -1;
         g_ltMod[0]  = m;
         g_ltTime[0] = (datetime)HistoryDealGetInteger(tk, DEAL_TIME);
         if(g_ltCount < 5) g_ltCount++;
        }
     }
   g_statDeals = total;
  }

//+------------------------------------------------------------------+
bool IsNewsBlackout()
  {
   if(!InpUseNewsFilter) return false;
   if(MQLInfoInteger(MQL_TESTER)) return false;

   datetime now = TimeTradeServer();
   if(now - g_newsCheck >= 300)
     {
      g_newsBlock = false;
      MqlCalendarValue v[];
      if(CalendarValueHistory(v, now - InpNewsAfter * 60, now + InpNewsBefore * 60, NULL, "USD"))
        {
         for(int i = 0; i < ArraySize(v); i++)
           {
            MqlCalendarEvent ev;
            if(CalendarEventById(v[i].event_id, ev))
               if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
                 {
                  g_newsBlock = true;
                  break;
                 }
           }
        }
      g_newsCheck = now;
     }
   return g_newsBlock;
  }

//+------------------------------------------------------------------+
bool SpreadOK()
  {
   double sp = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(sp > InpMaxSpread)
      return false;
   double t[1];
   if(InpMaxSpreadATR > 0.0 && CopyBuffer(hATR, 0, 1, 1, t) == 1 && t[0] > 0.0 &&
      sp > InpMaxSpreadATR * t[0])
      return false;
   return true;
  }

//+------------------------------------------------------------------+
bool CheckTradingStatus(string &why, bool checkSpread = true)
  {
   why = "";
   g_whyCode = -1;
   UpdateDailyStats();

   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   int gh = GetGMTHour(now);
   bool inSession = (gh >= InpLondonStart && gh < InpLondonEnd) ||
                    (gh >= InpNYStart && gh < InpNYEnd) ||
                    (InpTradeAsia && gh >= InpAsiaStart && gh < InpAsiaEnd);
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
      inSession = false;
   if(dt.day_of_week == 5 && gh >= InpFridayCloseGMT)
      inSession = false;
   if(!inSession)
     {
      why = StringFormat("Out of session (GMT %02d:%02d)", gh, dt.min);
      g_whyCode = R_SESSION;
      return false;
     }

   if(checkSpread && !SpreadOK())
     {
      double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
      why = StringFormat("Spread too high (%.2f)", spread);
      g_whyCode = R_SPREAD;
      return false;
     }

   if(IsNewsBlackout())
     {
      why = "USD news window";
      g_whyCode = R_NEWS;
      return false;
     }

   double t[1];
   if(CopyBuffer(hATR, 0, 1, 1, t) == 1)
     {
      double px = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double pct = (px > 0.0) ? t[0] / px * 100.0 : 0.0;
      if(pct < InpATRMinPct)
        {
         why = StringFormat("ATR too low (%.2f)", t[0]);
         g_whyCode = R_ATR;
         return false;
        }
      if(pct > InpATRMaxPct)
        {
         why = StringFormat("ATR too high (%.2f)", t[0]);
         g_whyCode = R_ATR;
         return false;
        }
     }

   if(g_tradesToday >= InpMaxTradesPerDay)
     {
      why = "Max trades/day reached";
      g_whyCode = R_MAXDAY;
      return false;
     }
   if(g_consecLosses >= InpMaxConsecLosses)
     {
      if(InpLossPauseBars <= 0)
        {
         why = "Loss streak limit reached";
         g_whyCode = R_PAUSE;
         return false;
        }
      if(TimeCurrent() < g_lastExitTime + (datetime)InpLossPauseBars * PeriodSeconds())
        {
         why = StringFormat("Loss streak pause (%d)", g_consecLosses);
         g_whyCode = R_PAUSE;
         return false;
        }
     }

   double startBal = AccountInfoDouble(ACCOUNT_BALANCE) - g_dailyPnL;
   double equityBase = (g_dayStartEquity > 0.0 ? g_dayStartEquity : startBal);
   double maxDailyLossCash = equityBase * InpMaxDailyLossPct / 100.0;
   double equityDrawdownToday = (g_dayStartEquity > 0.0)
                                ? g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY) : 0.0;
   if(g_dailyPnL <= -startBal * InpMaxDailyLossPct / 100.0 ||
      equityDrawdownToday >= maxDailyLossCash)
     {
      why = "Daily loss limit reached (balance/equity)";
      g_whyCode = R_DAYLOCK;
      return false;
     }

   return true;
  }

//+------------------------------------------------------------------+
bool SignalA(const MqlRates &r[], const double &atr[], SSignal &s)
  {
   if(!g_asiaValid || g_breakDone) return false;

   double a = atr[1];
   if(atr[1] < atr[4]) return false;

   double buf = InpA_BufferATR * a;
   double c1 = r[1].close, c2 = r[2].close;

   if(c1 > g_asiaHigh + buf && c2 <= g_asiaHigh + buf &&
      (c1 - g_asiaHigh) <= InpA_MaxChaseATR * a && r[1].close > r[1].open)
      s.dir = 1;
   else if(c1 < g_asiaLow - buf && c2 >= g_asiaLow - buf &&
           (g_asiaLow - c1) <= InpA_MaxChaseATR * a && r[1].close < r[1].open)
      s.dir = -1;
   else
      return false;

   s.slDist   = InpA_SL_ATR * a;
   s.tpDist   = s.slDist * InpA_RR;
   s.module   = 1;
   s.riskMult = InpA_RiskMult;
   return true;
  }

//+------------------------------------------------------------------+
bool SignalB(const MqlRates &r[], const double &atr[], const double &adx[],
             const double &pdi[], const double &mdi[],
             const double &emaF[], const double &emaS[],
             const bool htfUp, const bool htfDn, SSignal &s)
  {
   if(adx[1] < InpADXTrend) return false;
   if(InpRequireADXRising && adx[1] <= adx[2]) return false;

   double a = atr[1];
   int lb = MathMin(InpB_Lookback, 10);
   if(lb < 2) lb = 2;

   double candleRange = r[1].high - r[1].low;
   if(candleRange <= 0.0) return false;
   double bodyRatio = MathAbs(r[1].close - r[1].open) / candleRange;
   if(bodyRatio < InpB_MinBodyRatio) return false;

   bool bullCandle = r[1].close > r[1].open &&
                     r[1].close >= r[1].low + 0.70 * candleRange;
   bool bearCandle = r[1].close < r[1].open &&
                     r[1].close <= r[1].low + 0.30 * candleRange;

   bool up = emaF[1] > emaS[1] && emaS[1] > emaS[4] &&
             pdi[1] > mdi[1] &&
             (!InpUseHTFTrend || htfUp);
   bool dn = emaF[1] < emaS[1] && emaS[1] < emaS[4] &&
             mdi[1] > pdi[1] &&
             (!InpUseHTFTrend || htfDn);

   double tolB = InpB_TouchATR * a;
   double maxExt = InpB_MaxExtensionATR * a;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(up && bullCandle &&
      r[1].low <= emaF[1] + tolB &&
      r[1].close > emaF[1] && r[1].close > emaS[1] &&
      (r[1].close - emaF[1]) <= maxExt &&
      r[2].close > emaS[2])
     {
      double ll = r[1].low;
      for(int i = 2; i <= lb; i++)
         ll = MathMin(ll, r[i].low);

      double rawDist = ask - ll + 0.10 * a;
      if(rawDist <= 0.0 || rawDist > InpB_SLMaxATR * a)
         return false;

      double dist = MathMax(InpB_SLMinATR * a, rawDist);
      s.dir = 1;
      s.slDist = dist;
     }
   else if(dn && bearCandle &&
           r[1].high >= emaF[1] - tolB &&
           r[1].close < emaF[1] && r[1].close < emaS[1] &&
           (emaF[1] - r[1].close) <= maxExt &&
           r[2].close < emaS[2])
     {
      double hh = r[1].high;
      for(int i = 2; i <= lb; i++)
         hh = MathMax(hh, r[i].high);

      double rawDist = hh - bid + 0.10 * a;
      if(rawDist <= 0.0 || rawDist > InpB_SLMaxATR * a)
         return false;

      double dist = MathMax(InpB_SLMinATR * a, rawDist);
      s.dir = -1;
      s.slDist = dist;
     }
   else
      return false;

   s.tpDist   = s.slDist * InpB_RR;
   s.module   = 2;
   s.riskMult = InpB_RiskMult;
   return true;
  }

//+------------------------------------------------------------------+
bool SignalC(const MqlRates &r[], const double &atr[], const double &adx[],
             const double &emaF[], SSignal &s)
  {
   if(adx[1] >= InpADXRange) return false;

   double a = atr[1];
   if(a <= 0) return false;

   double candleRange = r[1].high - r[1].low;
   if(candleRange <= 0.0) return false;

   double dev = (r[1].close - emaF[1]) / a;

   if(dev > InpC_DevATR && r[1].close < r[1].open &&
      r[1].close <= r[1].low + 0.30 * candleRange)
     {
      s.dir      = -1;
      s.slDist   = InpC_SL_ATR * a;
      s.tpDist   = s.slDist * InpC_MinRR;
      s.module   = 3;
      s.riskMult = InpC_RiskMult;
      return true;
     }

   if(dev < -InpC_DevATR && r[1].close > r[1].open &&
      r[1].close >= r[1].low + 0.70 * candleRange)
     {
      s.dir      = 1;
      s.slDist   = InpC_SL_ATR * a;
      s.tpDist   = s.slDist * InpC_MinRR;
      s.module   = 3;
      s.riskMult = InpC_RiskMult;
      return true;
     }

   return false;
  }

//+------------------------------------------------------------------+
bool SignalD(const MqlRates &r[], const double &atr[], const double &adx[],
             const double &emaF[], const double &emaS[],
             const bool htfUp, const bool htfDn, SSignal &s)
  {
   if(!g_vpValid) return false;
   if(InpD_NeedADX && adx[1] < InpADXRange) return false;

   double a = atr[1];
   if(a <= 0) return false;

   double tol = InpD_TouchATR * a;
   double price = r[1].close;
   double candleRange = r[1].high - r[1].low;
   if(candleRange <= 0.0) return false;

   bool atVAL = MathAbs(price - g_val) <= tol;
   bool atPOC = MathAbs(price - g_poc) <= tol;
   if((atVAL || atPOC) && r[1].close > r[1].open &&
      r[1].close >= r[1].low + 0.60 * candleRange &&
      (!InpUseHTFTrend || htfUp))
     {
      double slDist = MathMax(InpD_SLMinATR * a,
                              price - g_val + InpD_SLBufferATR * a);
      if(slDist <= 0.0 || slDist > InpD_SLMaxATR * a) return false;

      double tpDist = slDist * InpD_DefaultRR;
      if(g_poc > price + slDist * InpD_MinRR)
         tpDist = g_poc - price;
      if(tpDist < slDist * InpD_MinRR)
         tpDist = slDist * InpD_MinRR;

      s.dir      = 1;
      s.slDist   = slDist;
      s.tpDist   = tpDist;
      s.module   = 4;
      s.riskMult = InpD_RiskMult;
      return true;
     }

   bool atVAH = MathAbs(price - g_vah) <= tol;
   if(atVAH && r[1].close < r[1].open &&
      r[1].close <= r[1].low + 0.40 * candleRange &&
      (!InpUseHTFTrend || htfDn))
     {
      double slDist = MathMax(InpD_SLMinATR * a,
                              g_vah - price + InpD_SLBufferATR * a);
      if(slDist <= 0.0 || slDist > InpD_SLMaxATR * a) return false;

      double tpDist = slDist * InpD_DefaultRR;
      if(g_poc < price - slDist * InpD_MinRR)
         tpDist = price - g_poc;
      if(tpDist < slDist * InpD_MinRR)
         tpDist = slDist * InpD_MinRR;

      s.dir      = -1;
      s.slDist   = slDist;
      s.tpDist   = tpDist;
      s.module   = 4;
      s.riskMult = InpD_RiskMult;
      return true;
     }

   return false;
  }

//+------------------------------------------------------------------+
double LossPerLot(const ENUM_ORDER_TYPE ot, const double price, const double sl)
  {
   double p = 0.0;
   if(OrderCalcProfit(ot, _Symbol, 1.0, price, sl, p) && p < 0.0)
      return -p;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tv > 0.0 && ts > 0.0)
      return MathAbs(price - sl) / ts * tv;
   return 0.0;
  }

//+------------------------------------------------------------------+
double CalcLots(const ENUM_ORDER_TYPE ot, const double price, const double sl, const double riskMult)
  {
   double risk = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0 * riskMult;
   double lpl  = LossPerLot(ot, price, sl);
   if(risk <= 0.0 || lpl <= 0.0)
      return 0.0;

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLots);
   if(step <= 0.0)
      step = 0.01;

   double lots = MathFloor((risk / lpl + 1e-10) / step) * step;
   if(lots < vmin)
     {
      if(!InpAllowMinLot)
         return 0.0;
      if(vmin * lpl > risk * InpMinLotRiskMult)
         return 0.0;
      lots = vmin;
     }
   if(lots > vmax)
      lots = vmax;

   int volDigits = 2;
   if(step < 0.01)  volDigits = 3;
   if(step < 0.001) volDigits = 4;
   return NormalizeDouble(lots, volDigits);
  }

//+------------------------------------------------------------------+
void OpenTrade(const SSignal &s)
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double price = (s.dir > 0) ? ask : bid;

   double minDist = (double)MathMax(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                                    SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;
   if(s.slDist <= minDist || s.tpDist <= minDist)
     {
      g_cnt[R_STOPS]++;
      return;
     }

   double sl = (s.dir > 0) ? price - s.slDist : price + s.slDist;
   double tp = (s.dir > 0) ? price + s.tpDist : price - s.tpDist;
   sl = NormalizeDouble(sl, _Digits);
   tp = NormalizeDouble(tp, _Digits);

   ENUM_ORDER_TYPE ot = (s.dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   double lots = CalcLots(ot, price, sl, s.riskMult);
   if(lots <= 0.0)
     {
      g_cnt[R_NOLOT]++;
      PrintFormat("Trade ignore : lot impossible (SL %.2f$, solde %.2f). Augmenter InpRiskPercent ou InpMinLotRiskMult.",
                  s.slDist, AccountInfoDouble(ACCOUNT_BALANCE));
      return;
     }

   double projectedAtSL = 0.0;
   double riskBudget = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0 * s.riskMult;
   double allowed = riskBudget * (InpAllowMinLot ? InpMinLotRiskMult : 1.0) * 1.02;
   if(!OrderCalcProfit(ot, _Symbol, lots, price, sl, projectedAtSL))
     {
      g_cnt[R_NOLOT]++;
      Print("Trade skipped: OrderCalcProfit failed");
      return;
     }
   if(projectedAtSL >= 0.0 || MathAbs(projectedAtSL) > allowed)
     {
      g_cnt[R_NOLOT]++;
      PrintFormat("Trade skipped: SL loss %.2f > allowed %.2f", MathAbs(projectedAtSL), allowed);
      return;
     }

   double margin = 0.0;
   if(!OrderCalcMargin(ot, _Symbol, lots, price, margin))
     {
      g_cnt[R_NOLOT]++;
      Print("Trade skipped: OrderCalcMargin failed");
      return;
     }
   if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.9)
     {
      g_cnt[R_NOLOT]++;
      Print("Insufficient margin, trade skipped");
      return;
     }

   string cm = InpComment + "_" + StringSubstr("ABCD", s.module - 1, 1);
   bool ok = (s.dir > 0) ? trade.Buy(lots, _Symbol, ask, sl, tp, cm)
                         : trade.Sell(lots, _Symbol, bid, sl, tp, cm);

   if(ok && trade.ResultRetcode() == TRADE_RETCODE_DONE)
     {
      g_initRisk  = s.slDist;
      g_posModule = s.module;
      g_hadPos    = true;
      g_cnt[R_OPENED]++;
      if(s.module == 1) g_breakDone = true;
      PrintFormat("[%s] %s lots=%.2f SL=%.2f TP=%.2f", cm, (s.dir > 0 ? "BUY" : "SELL"), lots, sl, tp);
      DrawArrow(s.dir, s.module, price, lots, sl, tp, s.atr);
      g_forcePanel = true;
     }
   else
     {
      g_cnt[R_FAIL]++;
      PrintFormat("Order failed, retcode=%d (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
//| Nouvelle barre : prepare l'evaluation (faite ensuite par TryEntry)|
//+------------------------------------------------------------------+
void OnNewBar()
  {
   UpdateDay();
   ComputeSR();
   if(InpEnableD)
      ComputeVP();     // CORRECTIF : en backtest sans visuel le VP n'etait jamais calcule

   ulong tk;
   bool inPos = FindPosition(tk);
   string why;
   bool allowed = CheckTradingStatus(why, false);

   string st = inPos ? "IN POSITION" : (allowed ? "ACTIVE" : "PAUSED - " + why);
   string key = st;
   int cut = StringFind(key, " (");
   if(cut > 0) key = StringSubstr(key, 0, cut);
   if(key != g_lastStatus)
     {
      PrintFormat("[STATUS] %s | %s | trades %d/%d | loss streak %d/%d | daily P/L %.2f",
                  TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES), st,
                  g_tradesToday, InpMaxTradesPerDay, g_consecLosses, InpMaxConsecLosses, g_dailyPnL);
      g_lastStatus = key;
     }

   g_evalDone = false;
   g_spreadBlocked = false;
  }

//+------------------------------------------------------------------+
//| Entree : une evaluation par barre, retentee si le spread est haut |
//+------------------------------------------------------------------+
void TryEntry(const datetime barTime)
  {
   if(TimeCurrent() - barTime > InpEntryWindowSec)
     {
      g_evalDone = true;
      if(g_spreadBlocked)
         g_cnt[R_SPREAD]++;
      return;
     }
   if(!SpreadOK())
     {
      g_spreadBlocked = true;
      return;
     }
   g_evalDone = true;
   EvaluateEntry();
  }

//+------------------------------------------------------------------+
void EvaluateEntry()
  {
   ulong tk;
   if(FindPosition(tk))
     {
      g_cnt[R_INPOS]++;
      return;
     }

   string why;
   if(!CheckTradingStatus(why, false))
     {
      if(g_whyCode >= 0 && g_whyCode < R_N)
         g_cnt[g_whyCode]++;
      return;
     }

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, _Period, 0, 12, r) < 12)
     { g_cnt[R_DATA]++; return; }

   double atr[], adx[], pdi[], mdi[], emaF[], emaS[];
   ArraySetAsSeries(atr, true);  ArraySetAsSeries(adx, true);
   ArraySetAsSeries(pdi, true);  ArraySetAsSeries(mdi, true);
   ArraySetAsSeries(emaF, true); ArraySetAsSeries(emaS, true);

   if(CopyBuffer(hATR, 0, 0, 8, atr) < 8)   { g_cnt[R_DATA]++; return; }
   if(CopyBuffer(hADX, 0, 0, 8, adx) < 8)   { g_cnt[R_DATA]++; return; }
   if(CopyBuffer(hADX, 1, 0, 8, pdi) < 8)   { g_cnt[R_DATA]++; return; }
   if(CopyBuffer(hADX, 2, 0, 8, mdi) < 8)   { g_cnt[R_DATA]++; return; }
   if(CopyBuffer(hEMAF, 0, 0, 8, emaF) < 8) { g_cnt[R_DATA]++; return; }
   if(CopyBuffer(hEMAS, 0, 0, 8, emaS) < 8) { g_cnt[R_DATA]++; return; }

   double htfF[], htfS[];
   ArraySetAsSeries(htfF, true);
   ArraySetAsSeries(htfS, true);
   int gotHTFF = CopyBuffer(hHTFF, 0, 0, 4, htfF);
   int gotHTFS = CopyBuffer(hHTFS, 0, 0, 4, htfS);
   bool haveHTF = (gotHTFF >= 4 && gotHTFS >= 4);
   if(InpUseHTFTrend && !haveHTF)
     { g_cnt[R_DATA]++; return; }
   bool htfUp = haveHTF && htfF[1] > htfS[1] && htfS[1] >= htfS[3];
   bool htfDn = haveHTF && htfF[1] < htfS[1] && htfS[1] <= htfS[3];

   double px = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double atrPct = (px > 0.0) ? atr[1] / px * 100.0 : 0.0;
   if(atrPct < InpATRMinPct || atrPct > InpATRMaxPct)
     { g_cnt[R_ATR]++; return; }

   SSignal s;
   s.dir = 0; s.slDist = 0; s.tpDist = 0; s.module = 0; s.riskMult = 1.0; s.atr = atr[1];

   bool found = false;
   if(InpEnableA)           found = SignalA(r, atr, s);
   if(!found && InpEnableD) found = SignalD(r, atr, adx, emaF, emaS, htfUp, htfDn, s);
   if(!found && InpEnableB) found = SignalB(r, atr, adx, pdi, mdi, emaF, emaS, htfUp, htfDn, s);
   if(!found && InpEnableC) found = SignalC(r, atr, adx, emaF, s);

   if(!found || s.dir == 0)
     { g_cnt[R_NOSIG]++; return; }

   g_cnt[R_SIGA + s.module - 1]++;

   if(InpUseFixedStops && !(s.module == 4 && InpD_UseVPStops))
     {
      s.slDist = InpFixedSL;
      s.tpDist = InpFixedTP;
     }
   OpenTrade(s);
  }

//+------------------------------------------------------------------+
void ManagePosition()
  {
   ulong tk;
   if(!FindPosition(tk))
     {
      if(g_hadPos)
        {
         g_hadPos = false;
         g_forcePanel = true;
         g_forceStats = true;
        }
      g_initRisk = 0;
      return;
     }
   g_hadPos = true;

   long   type = PositionGetInteger(POSITION_TYPE);
   double open = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl   = PositionGetDouble(POSITION_SL);
   double tp   = PositionGetDouble(POSITION_TP);
   datetime ot = (datetime)PositionGetInteger(POSITION_TIME);

   //--- perte journaliere (equity)
   if(InpMaxDailyLossPct > 0.0 && g_dayStartEquity > 0.0)
     {
      double equityFloor = g_dayStartEquity * (1.0 - InpMaxDailyLossPct / 100.0);
      if(AccountInfoDouble(ACCOUNT_EQUITY) <= equityFloor)
        {
         Print("Daily equity loss limit reached: closing position");
         trade.PositionClose(tk);
         return;
        }
     }

   //--- fermeture du vendredi soir
   MqlDateTime dtn;
   TimeToStruct(TimeCurrent(), dtn);
   if(dtn.day_of_week == 5 && GetGMTHour(TimeCurrent()) >= InpFridayCloseGMT)
     {
      Print("Friday close: closing position");
      trade.PositionClose(tk);
      return;
     }

   //--- sortie temporelle
   if(InpMaxBars > 0 && (long)(TimeCurrent() - ot) > (long)InpMaxBars * PeriodSeconds())
     {
      trade.PositionClose(tk);
      return;
     }

   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(hATR, 0, 0, 2, atr) < 2) return;

   if(g_initRisk <= 0)
     {
      double d = (type == POSITION_TYPE_BUY) ? open - sl : sl - open;
      g_initRisk = (sl > 0.0 && d > 0.0) ? d : 1.5 * atr[1];
     }

   bool buy = (type == POSITION_TYPE_BUY);
   double price = buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double profit = buy ? price - open : open - price;
   if(profit < InpBE_R * g_initRisk) return;

   double minDist = (double)MathMax(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                                    SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;
   double minStep = 0.05 * atr[1];
   bool trailOn = (g_posModule != 3) && (profit >= InpTrailStart_R * g_initRisk);
   double newSL;

   if(buy)
     {
      newSL = open + InpBE_Offset_R * g_initRisk;
      if(trailOn) newSL = MathMax(newSL, price - InpTrailATR * atr[1]);
      if(price - newSL < minDist) return;
      if(sl == 0 || newSL > sl + minStep)
         trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
     }
   else
     {
      newSL = open - InpBE_Offset_R * g_initRisk;
      if(trailOn) newSL = MathMin(newSL, price + InpTrailATR * atr[1]);
      if(newSL - price < minDist) return;
      if(sl == 0 || newSL < sl - minStep)
         trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
     }
  }

//+==================================================================+
//|                         AFFICHAGE                                |
//+==================================================================+
void RefreshVisuals(bool force)
  {
   if(!g_draw) return;
   ulong now = GetTickCount64();
   if(!force && !g_forcePanel && now - g_lastPanel < 1000) return;
   g_lastPanel  = now;
   g_forcePanel = false;

   if(force)
     {
      ComputeSR();
      ComputeVP();
      DrawEMALines();
      DrawAsiaRange();
      DrawSR();
      DrawVP();
     }
   PanelUpdate();
   ChartRedraw(0);
  }

void ApplyTheme()
  {
   ChartSetInteger(0, CHART_MODE, CHART_CANDLES);
   ChartSetInteger(0, CHART_COLOR_BACKGROUND, C'14,17,23');
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, C'160,170,185');
   ChartSetInteger(0, CHART_COLOR_GRID, C'30,36,46');
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_COLOR_CHART_LINE, C'200,205,215');
  }

void ApplyCandleColors()
  {
   ChartSetInteger(0, CHART_MODE, CHART_CANDLES);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, InpColCandleBull);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, InpColCandleBear);
   ChartSetInteger(0, CHART_COLOR_CHART_UP,    InpColCandleBull);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN,  InpColCandleBear);
  }

void AddChartIndicators()
  {
   if(!InpShowSubwindows) return;

   int w = (int)ChartGetInteger(0, CHART_WINDOWS_TOTAL);
   if(ChartIndicatorAdd(0, w, hADX))
     {
      g_adxWin  = w;
      g_adxName = ChartIndicatorName(0, w, 0);
     }
   w = (int)ChartGetInteger(0, CHART_WINDOWS_TOTAL);
   if(ChartIndicatorAdd(0, w, hATR))
     {
      g_atrWin  = w;
      g_atrName = ChartIndicatorName(0, w, 0);
     }
  }

//+------------------------------------------------------------------+
//| ComputeVP : Volume Profile avec HVN/LVN strict (1 seul nœud)     |
//+------------------------------------------------------------------+
void ComputeVP()
  {
   int target = MathMax(50, InpVPBars);
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int got = CopyRates(_Symbol, _Period, 1, target, r);
   if(got < 20) { g_vpValid = false; return; }
   int n = got;

   if(g_vpBar == r[0].time && g_vpValid) return;

   double hi = r[0].high, lo = r[0].low;
   for(int i = 1; i < n; i++)
     {
      if(r[i].high > hi) hi = r[i].high;
      if(r[i].low  < lo) lo = r[i].low;
     }
   if(hi <= lo) { g_vpValid = false; return; }

   int bins = MathMax(10, InpVPBins);
   double step = (hi - lo) / bins;
   if(step <= 0.0) { g_vpValid = false; return; }

   double vol[];
   ArrayResize(vol, bins);
   ArrayInitialize(vol, 0.0);

   for(int i = 0; i < n; i++)
     {
      double cl = (r[i].high + r[i].low + r[i].close) / 3.0;
      int idx = (int)MathFloor((cl - lo) / step);
      if(idx < 0) idx = 0;
      if(idx >= bins) idx = bins - 1;
      vol[idx] += (double)r[i].tick_volume;
     }

   double totalVol = 0.0;
   for(int i = 0; i < bins; i++) totalVol += vol[i];
   if(totalVol <= 0.0) { g_vpValid = false; return; }

   int pocIdx = 0;
   for(int i = 1; i < bins; i++)
      if(vol[i] > vol[pocIdx]) pocIdx = i;
   g_poc = lo + (pocIdx + 0.5) * step;

   double vaVol = vol[pocIdx];
   int up = pocIdx, dn = pocIdx;
   double targetVa = totalVol * InpVPValueArea / 100.0;
   while(vaVol < targetVa && (up < bins - 1 || dn > 0))
     {
      double upVol = (up < bins - 1) ? vol[up + 1] : -1.0;
      double dnVol = (dn > 0)         ? vol[dn - 1] : -1.0;
      if(upVol >= dnVol && up < bins - 1) { up++; vaVol += upVol; }
      else if(dn > 0)                     { dn--; vaVol += dnVol; }
      else break;
     }
   g_vah = lo + (up + 1) * step;
   g_val = lo + dn * step;

   // --- HVN / LVN : on garde UNIQUEMENT le nœud le plus fort et le plus faible ---
   ArrayResize(g_hvn, 1);
   ArrayResize(g_lvn, 1);
   int hIdx = 0, lIdx = 0;
   for(int i = 1; i < bins; i++)
     {
      if(vol[i] > vol[hIdx]) hIdx = i;
      if(vol[i] < vol[lIdx] && vol[i] > 0) lIdx = i;
     }
   g_hvn[0] = lo + (hIdx + 0.5) * step;
   g_lvn[0] = lo + (lIdx + 0.5) * step;

   g_vpStep  = step;
   g_vpT1    = r[n - 1].time;
   g_vpBar   = r[0].time;
   g_vpValid = true;
  }

//+------------------------------------------------------------------+
//| Primitives graphiques                                            |
//+------------------------------------------------------------------+
void LabelSet(const string name, int x, int y, const string text, color clr, int size,
              const string font, ENUM_ANCHOR_POINT anchor)
  {
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, anchor);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetString(0, name, OBJPROP_FONT, font);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void RectSet(const string name, int x, int y, int w, int h, color bg, color border)
  {
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, border);
  }

void SetSeg(const string name, datetime t1, double p1, datetime t2, double p2,
            color clr, int width, ENUM_LINE_STYLE style = STYLE_SOLID, const string tip = "", bool ray_right = false)
  {
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2)) return;
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
     }
   else
     {
      ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
      ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
     }
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, ray_right);
   if(tip != "") ObjectSetString(0, name, OBJPROP_TOOLTIP, tip);
  }

void TextSet(const string name, datetime t, double p, const string text, color clr)
  {
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, p)) return;
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
     }
   else
      ObjectMove(0, name, 0, t, p);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void DrawEMALines()
  {
   if(!InpShowEMA) return;

   int n = MathMax(10, InpEMABars);
   int need = n + 2;
   double f[], s[];
   datetime tm[];
   ArraySetAsSeries(f, true);
   ArraySetAsSeries(s, true);
   ArraySetAsSeries(tm, true);
   if(CopyBuffer(hEMAF, 0, 0, need, f) < need) return;
   if(CopyBuffer(hEMAS, 0, 0, need, s) < need) return;
   if(CopyTime(_Symbol, _Period, 0, need, tm) < need) return;

   for(int k = 0; k < n; k++)
     {
      int a = k + 1, b = k + 2;
      SetSeg("GSL_F" + IntegerToString(k), tm[b], f[b], tm[a], f[a], InpColEMAFast, 2);
      SetSeg("GSL_S" + IntegerToString(k), tm[b], s[b], tm[a], s[a], InpColEMASlow, 2);
     }
  }

//+------------------------------------------------------------------+
//| ComputeSR : support / résistance STRICTEMENT sur 48 bougies      |
//+------------------------------------------------------------------+
bool ComputeSR()
  {
   int target = MathMax(5, InpSRBars);
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int got = CopyRates(_Symbol, _Period, 1, target, r);
   if(got < 5) return false;
   int n = got;

   double hi = r[0].high, lo = r[0].low;
   for(int i = 1; i < n; i++)
     {
      if(r[i].high > hi) hi = r[i].high;
      if(r[i].low  < lo) lo = r[i].low;
     }
   g_res  = hi;
   g_sup  = lo;
   g_srT1 = r[n - 1].time;
   return true;
  }

//+------------------------------------------------------------------+
//| DrawSR : ligne tracée seulement sur les 48 dernières bougies     |
//+------------------------------------------------------------------+
void DrawSR()
  {
   if(!InpShowSR || g_sup <= 0 || g_res <= 0) return;

   ObjectDelete(0, "GSS_SUP");
   ObjectDelete(0, "GSS_RES");
   ObjectDelete(0, "GSS_SUPT");
   ObjectDelete(0, "GSS_REST");

   int n = MathMax(5, InpSRBars);
   datetime tEnd = iTime(_Symbol, _Period, 0);

   SetSeg("GSS_SUP", g_srT1, g_sup, tEnd, g_sup,
          InpSupportColor, InpSRLineWidth, STYLE_SOLID,
          StringFormat("Support %.2f (%d bars)", g_sup, n), true);
   SetSeg("GSS_RES", g_srT1, g_res, tEnd, g_res,
          InpResistColor, InpSRLineWidth, STYLE_SOLID,
          StringFormat("Resistance %.2f (%d bars)", g_res, n), true);
   TextSet("GSS_SUPT", tEnd, g_sup, StringFormat("  S  %.2f", g_sup), InpSupportColor);
   TextSet("GSS_REST", tEnd, g_res, StringFormat("  R  %.2f", g_res), InpResistColor);
  }

//+------------------------------------------------------------------+
//| VPLine / VPDashLine                                              |
//+------------------------------------------------------------------+
void VPLine(const string id, double p, const string label, datetime t1, datetime t2,
            color clr, int width, ENUM_LINE_STYLE style)
  {
   SetSeg("GSV_" + id, t1, p, t2, p, clr, width, style, StringFormat("%s %.2f", label, p), true);
   TextSet("GSV_" + id + "T", t2 + 2 * PeriodSeconds(), p, StringFormat("%s  %.2f", label, p), clr);
  }

void VPDashLine(const string id, double p, const string label, datetime t2, color clr, int width)
  {
   int n = MathMax(20, InpVPBars);
   datetime tm[];
   ArraySetAsSeries(tm, false);
   int got = CopyTime(_Symbol, _Period, 1, n, tm);
   if(got < 2) return;
   int dash = MathMax(1, InpDashBars), gap = MathMax(1, InpGapBars);
   string tip = StringFormat("%s %.2f", label, p);
   int k = 0;
   for(int i = 0; i < got; i += dash + gap)
     {
      int j = i + dash;
      datetime e = (j < got) ? tm[j] : t2;
      SetSeg("GSV_" + id + "_D" + IntegerToString(k), tm[i], p, e, p, clr, width, STYLE_SOLID, tip, false);
      ObjectSetDouble(0, "GSV_" + id + "_D" + IntegerToString(k), OBJPROP_PRICE, 0, p);
      ObjectSetDouble(0, "GSV_" + id + "_D" + IntegerToString(k), OBJPROP_PRICE, 1, p);
      k++;
     }
   while(ObjectFind(0, "GSV_" + id + "_D" + IntegerToString(k)) >= 0)
     {
      ObjectDelete(0, "GSV_" + id + "_D" + IntegerToString(k));
      k++;
     }
   TextSet("GSV_" + id + "T", t2 + 2 * PeriodSeconds(), p, StringFormat("%s  %.2f", label, p), clr);
  }

//+------------------------------------------------------------------+
//| DrawVP : POC / VAH / VAL / HVN / LVN sans aucun doublon          |
//+------------------------------------------------------------------+
void DrawVP()
  {
   if(!InpShowVP) return;

   ObjectsDeleteAll(0, "GSV_");

   if(!g_vpValid) return;

   datetime tEnd = iTime(_Symbol, _Period, 0) + 5 * PeriodSeconds();

   // POC / VAH / VAL : lignes continues + valeurs
   VPLine("POC", g_poc, "POC", g_vpT1, tEnd, InpColVA, MathMax(1, InpVAWidth), STYLE_SOLID);
   VPLine("VAH", g_vah, "VAH", g_vpT1, tEnd, InpColVA, MathMax(1, InpVAWidth), STYLE_SOLID);
   VPLine("VAL", g_val, "VAL", g_vpT1, tEnd, InpColVA, MathMax(1, InpVAWidth), STYLE_SOLID);

   // HVN / LVN : lignes discontinues + valeurs
   if(ArraySize(g_hvn) > 0)
      VPDashLine("H0", g_hvn[0], "HVN", tEnd, InpColVP, MathMax(1, InpNodeWidth));
   if(ArraySize(g_lvn) > 0)
      VPDashLine("L0", g_lvn[0], "LVN", tEnd, InpColVP, MathMax(1, InpNodeWidth));
  }

//+------------------------------------------------------------------+
//| Range asiatique                                                  |
//+------------------------------------------------------------------+
void DrawAsiaRange()
  {
   if(!InpShowAsia) return;

   if(!g_asiaValid)
     {
      ObjectDelete(0, "GSR_BOX");
      ObjectDelete(0, "GSR_HI");
      ObjectDelete(0, "GSR_LO");
      return;
     }

   datetime s = g_dayStart + (InpAsiaStart + InpBrokerGMTOffset) * 3600;
   datetime e = g_dayStart + (InpAsiaEnd   + InpBrokerGMTOffset) * 3600;
   datetime x = g_dayStart + (InpNYEnd     + InpBrokerGMTOffset) * 3600;

   if(ObjectFind(0, "GSR_BOX") < 0)
     {
      if(ObjectCreate(0, "GSR_BOX", OBJ_RECTANGLE, 0, s, g_asiaHigh, e, g_asiaLow))
        {
         ObjectSetInteger(0, "GSR_BOX", OBJPROP_COLOR, C'25,50,60');
         ObjectSetInteger(0, "GSR_BOX", OBJPROP_FILL, true);
         ObjectSetInteger(0, "GSR_BOX", OBJPROP_BACK, true);
         ObjectSetInteger(0, "GSR_BOX", OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, "GSR_BOX", OBJPROP_HIDDEN, true);
        }
     }
   else
     {
      ObjectSetInteger(0, "GSR_BOX", OBJPROP_TIME, 0, s);
      ObjectSetDouble(0, "GSR_BOX", OBJPROP_PRICE, 0, g_asiaHigh);
      ObjectSetInteger(0, "GSR_BOX", OBJPROP_TIME, 1, e);
      ObjectSetDouble(0, "GSR_BOX", OBJPROP_PRICE, 1, g_asiaLow);
     }
   ObjectSetString(0, "GSR_BOX", OBJPROP_TOOLTIP, "Asian range");

   SetSeg("GSR_HI", e, g_asiaHigh, x, g_asiaHigh, InpColAsia, 1, STYLE_DASH,
          StringFormat("Asia High %.2f", g_asiaHigh), false);
   SetSeg("GSR_LO", e, g_asiaLow, x, g_asiaLow, InpColAsia, 1, STYLE_DASH,
          StringFormat("Asia Low %.2f", g_asiaLow), false);
  }

//+------------------------------------------------------------------+
//| Flèche BUY / SELL                                                |
//+------------------------------------------------------------------+
void DrawArrow(int dir, int module, double price, double lots, double sl, double tp, double atr)
  {
   if(!g_draw || !InpShowArrows) return;

   string nm = "GSA_" + (string)(long)TimeCurrent() + "_" + IntegerToString(g_arrowN++);
   datetime t = iTime(_Symbol, _Period, 0);
   double off = 0.3 * atr;
   double p = (dir > 0) ? price - off : price + off;
   ENUM_OBJECT ty = (dir > 0) ? OBJ_ARROW_UP : OBJ_ARROW_DOWN;

   if(ObjectCreate(0, nm, ty, 0, t, p))
     {
      ObjectSetInteger(0, nm, OBJPROP_COLOR, (dir > 0) ? InpColBuy : InpColSell);
      ObjectSetInteger(0, nm, OBJPROP_WIDTH, 3);
      ObjectSetInteger(0, nm, OBJPROP_ANCHOR, (dir > 0) ? ANCHOR_TOP : ANCHOR_BOTTOM);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      string mod = (module >= 1 && module <= 4) ? StringSubstr("ABCD", module - 1, 1) : "?";
      ObjectSetString(0, nm, OBJPROP_TOOLTIP,
                      StringFormat("%s [%s]  %.2f lots | Entry %.2f | SL %.2f | TP %.2f",
                                   (dir > 0 ? "BUY" : "SELL"), mod, lots, price, sl, tp));
     }
  }

//+------------------------------------------------------------------+
//| Panneau                                                          |
//+------------------------------------------------------------------+
int LastTradesShown() { return MathMin(5, MathMax(1, InpLastTrades)); }
int PanelRows()       { return 26 + LastTradesShown(); }

void PanelInit()
  {
   g_px = InpPanelX;
   g_py = InpPanelY;
   int h = HEAD_H + PanelRows() * ROW_H + 10;
   RectSet("GSP_BG", g_px, g_py, PANEL_W, h, C'20,24,33', C'45,52,66');
   RectSet("GSP_HD", g_px, g_py, PANEL_W, HEAD_H, C'27,58,107', C'27,58,107');
  }

void Sec(const string title)
  {
   int y = g_py + HEAD_H + 4 + g_row * ROW_H;
   RectSet("GSP_S" + IntegerToString(g_row), g_px + 8, y + ROW_H - 3, PANEL_W - 16, 1, C'45,52,66', C'45,52,66');
   LabelSet("GSP_L" + IntegerToString(g_row), g_px + 10, y, title, COL_ACCENT, 8, "Arial Bold", ANCHOR_LEFT_UPPER);
   LabelSet("GSP_V" + IntegerToString(g_row), g_px + PANEL_W - 10, y, " ", clrWhite, 8, "Arial", ANCHOR_RIGHT_UPPER);
   g_row++;
  }

void Row(const string label, const string value, color vc = clrWhite)
  {
   int y = g_py + HEAD_H + 4 + g_row * ROW_H;
   LabelSet("GSP_L" + IntegerToString(g_row), g_px + 10, y, label, COL_LABEL, 8, "Arial", ANCHOR_LEFT_UPPER);
   LabelSet("GSP_V" + IntegerToString(g_row), g_px + PANEL_W - 10, y, value, vc, 8, "Arial", ANCHOR_RIGHT_UPPER);
   g_row++;
  }

color PnLColor(double v)
  {
   if(v > 0) return COL_GREEN;
   if(v < 0) return COL_RED;
   return clrWhite;
  }

string SessionName(int gh)
  {
   if(gh >= InpLondonStart && gh < InpLondonEnd) return "LONDON";
   if(gh >= InpNYStart && gh < InpNYEnd)         return "NEW YORK";
   if(gh >= InpAsiaStart && gh < InpAsiaEnd)     return "ASIA";
   return "OFF HOURS";
  }

string FmtTime(datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return StringFormat("%02d.%02d %02d:%02d", d.mon, d.day, d.hour, d.min);
  }

bool GetSnapshot()
  {
   double a[], x[], p[], m[], f[], sl[];
   ArraySetAsSeries(a, true);  ArraySetAsSeries(x, true);
   ArraySetAsSeries(p, true);  ArraySetAsSeries(m, true);
   ArraySetAsSeries(f, true);  ArraySetAsSeries(sl, true);
   if(CopyBuffer(hATR, 0, 0, 6, a) < 6)   return false;
   if(CopyBuffer(hADX, 0, 0, 6, x) < 6)   return false;
   if(CopyBuffer(hADX, 1, 0, 6, p) < 6)   return false;
   if(CopyBuffer(hADX, 2, 0, 6, m) < 6)   return false;
   if(CopyBuffer(hEMAF, 0, 0, 6, f) < 6)  return false;
   if(CopyBuffer(hEMAS, 0, 0, 6, sl) < 6) return false;
   g_atrV = a[1];  g_atr4 = a[4];
   g_adx = x[1];   g_pdi = p[1];  g_mdi = m[1];
   g_emaF = f[1];  g_emaS = sl[1];
   g_close1 = iClose(_Symbol, _Period, 1);
   return true;
  }

string RegimeText(color &c)
  {
   c = clrSilver;
   bool impulse = g_asiaValid && !g_breakDone && g_atrV >= g_atr4 &&
                  (g_close1 > g_asiaHigh + InpA_BufferATR * g_atrV ||
                   g_close1 < g_asiaLow  - InpA_BufferATR * g_atrV);
   if(impulse && InpEnableA)
     {
      c = COL_ACCENT;
      return "IMPULSE  >> A";
     }
   if(g_adx >= InpADXTrend)
     {
      string mod = InpEnableB ? ">> B" : ">> B (off)";
      if(g_emaF > g_emaS && g_pdi > g_mdi) { c = COL_GREEN; return "UPTREND  " + mod; }
      if(g_emaF < g_emaS && g_mdi > g_pdi) { c = COL_RED;   return "DOWNTREND  " + mod; }
      return "MIXED TREND";
     }
   if(g_adx < InpADXRange)
     {
      c = COL_BLUE;
      return InpEnableC ? "RANGE  >> C" : "RANGE  >> C (off)";
     }
   c = clrGray;
   return "NEUTRAL ZONE  (no trade)";
  }

string ModuleRow(int m, color &c)
  {
   int n = g_stTrades[m];
   string wr = (n > 0) ? StringFormat("%.0f%%", 100.0 * g_stWins[m] / n) : "--";
   c = PnLColor(g_stNet[m]);
   return StringFormat("%d tr  |  %s  |  %+.2f", n, wr, g_stNet[m]);
  }

void PanelUpdate()
  {
   if(!InpShowPanel) return;
   if(g_dayStart == 0) g_dayStart = iTime(_Symbol, PERIOD_D1, 0);

   bool snap = GetSnapshot();
   string why = "";
   bool allowed = CheckTradingStatus(why);

   ulong nowTick = GetTickCount64();
   if(g_forceStats || nowTick - g_lastStat > 5000)
     {
      UpdateGlobalStats();
      g_lastStat   = nowTick;
      g_forceStats = false;
     }

   ulong tk;
   bool inPos = FindPosition(tk);

   string stText;
   color  stCol;
   if(inPos)        { stText = "IN POSITION";     stCol = COL_BLUE;  }
   else if(allowed) { stText = "ACTIVE";          stCol = COL_GREEN; }
   else             { stText = "PAUSED - " + why; stCol = COL_AMBER; }

   LabelSet("GSP_T",  g_px + 10,          g_py + 8,  "GOLD SCALPER  M5  v9", clrWhite, 10, "Arial Bold", ANCHOR_LEFT_UPPER);
   LabelSet("GSP_ST", g_px + PANEL_W - 10, g_py + 10, stText,             stCol,    8,  "Arial Bold", ANCHOR_RIGHT_UPPER);

   g_row = 0;
   color c;

   Sec("MARKET");
   if(snap)
     {
      string rt = RegimeText(c);
      Row("Regime", rt, c);
      Row("ADX / ATR", StringFormat("%.1f  /  $%.2f", g_adx, g_atrV));
      Row(StringFormat("EMA %d / %d", InpEMAFast, InpEMASlow),
          StringFormat("%.2f  /  %.2f", g_emaF, g_emaS));
     }
   else
     {
      Row("Regime", "loading...", clrGray);
      Row("ADX / ATR", "--");
      Row(StringFormat("EMA %d / %d", InpEMAFast, InpEMASlow), "--");
     }
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int gh = GetGMTHour(TimeCurrent());
   Row("Spread / Session", StringFormat("$%.2f  /  %s", spread, SessionName(gh)),
       (spread > InpMaxSpread) ? COL_AMBER : clrWhite);
   Row("Asia range", g_asiaValid ? StringFormat("%.2f  -  %.2f", g_asiaHigh, g_asiaLow) : "pending", clrWhite);
   Row(StringFormat("Support / Resistance (%d bars)", MathMax(5, InpSRBars)),
       (g_sup > 0) ? StringFormat("%.2f  /  %.2f", g_sup, g_res) : "--", clrWhite);
   Row("POC / VAH / VAL", g_vpValid ? StringFormat("%.2f  /  %.2f  /  %.2f", g_poc, g_vah, g_val) : "--", clrWhite);

   // Affichage simplifié : 1 seul HVN et 1 seul LVN maximum
   string hs = (ArraySize(g_hvn) > 0) ? DoubleToString(g_hvn[0], 2) : "--";
   string ls = (ArraySize(g_lvn) > 0) ? DoubleToString(g_lvn[0], 2) : "--";
   Row("HVN / LVN", hs + "  |  " + ls, clrWhite);

   Sec("ACCOUNT");
   Row(StringFormat("Balance / Equity (%s)", AccountInfoString(ACCOUNT_CURRENCY)),
       StringFormat("%.2f  /  %.2f", AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY)));
   if(inPos)
     {
      bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double fl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      string mod = (g_posModule > 0) ? StringSubstr("ABCD", g_posModule - 1, 1) : "?";
      Row("Position", StringFormat("%s %.2f [%s]   %+.2f", (isBuy ? "BUY" : "SELL"),
                                   PositionGetDouble(POSITION_VOLUME), mod, fl), PnLColor(fl));
     }
   else
      Row("Position", "None", clrSilver);

   double startBal = AccountInfoDouble(ACCOUNT_BALANCE) - g_dailyPnL;
   double dPct = (startBal > 0) ? g_dailyPnL / startBal * 100.0 : 0.0;
   Sec("TODAY");
   Row("Daily P/L", StringFormat("%+.2f  (%+.2f%%)", g_dailyPnL, dPct), PnLColor(g_dailyPnL));
   Row("Trades today / Loss streak", StringFormat("%d/%d   |   %d/%d",
       g_tradesToday, InpMaxTradesPerDay, g_consecLosses, InpMaxConsecLosses));

   int nT = g_stTrades[0] + g_stTrades[1] + g_stTrades[2] + g_stTrades[3] + g_stTrades[4];
   int nW = g_stWins[0]   + g_stWins[1]   + g_stWins[2]   + g_stWins[3]   + g_stWins[4];
   double net = g_stNet[0] + g_stNet[1] + g_stNet[2] + g_stNet[3] + g_stNet[4];
   double pf = (g_grossL > 0) ? g_grossP / g_grossL : (g_grossP > 0 ? 99.99 : 0.0);
   Sec("PERFORMANCE");
   Row("Trades (W / L)", StringFormat("%d   (%d / %d)", nT, nW, nT - nW));
   Row("Win rate", (nT > 0) ? StringFormat("%.1f%%", 100.0 * nW / nT) : "--");
   Row("Profit factor", (nT > 0) ? StringFormat("%.2f", pf) : "--",
       (nT > 0) ? (pf >= 1.3 ? COL_GREEN : (pf >= 1.0 ? COL_AMBER : COL_RED)) : clrWhite);
   Row("Net / Max DD", StringFormat("%+.2f  /  -%.2f", net, g_maxDD), PnLColor(net));

   Sec("MODULES");
   Row(InpEnableA ? "A  Breakout"     : "A  Breakout (off)",     ModuleRow(1, c), c);
   Row(InpEnableB ? "B  Pullback"     : "B  Pullback (off)",     ModuleRow(2, c), c);
   Row(InpEnableC ? "C  Mean reversion" : "C  Mean reversion (off)", ModuleRow(3, c), c);
   Row(InpEnableD ? "D  Volume profile" : "D  Volume profile (off)", ModuleRow(4, c), c);

   Sec("LAST TRADES");
   int nShow = LastTradesShown();
   for(int i = 0; i < nShow; i++)
     {
      if(i < g_ltCount)
        {
         string md = (g_ltMod[i] > 0) ? StringSubstr("ABCD", g_ltMod[i] - 1, 1) : "?";
         Row(StringFormat("%d. %s [%s]   %s", i + 1, (g_ltDir[i] > 0 ? "BUY" : "SELL"), md, FmtTime(g_ltTime[i])),
             StringFormat("%+.2f", g_ltPnl[i]), PnLColor(g_ltPnl[i]));
        }
      else
         Row(StringFormat("%d.  --", i + 1), " ", clrSilver);
     }
  }
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Critere d'optimisation : ignore les tests a trop peu de trades   |
//+------------------------------------------------------------------+
double OnTester()
  {
   double trades = TesterStatistics(STAT_TRADES);
   double np     = TesterStatistics(STAT_PROFIT);
   double pf     = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd     = TesterStatistics(STAT_EQUITYDD_PERCENT);
   if(trades < 60.0 || np <= 0.0)
      return 0.0;
   return (np / MathMax(1.0, dd)) * MathMin(pf, 3.0) * MathSqrt(trades) / 10.0;
  }
//+------------------------------------------------------------------+