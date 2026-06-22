import math

ADR_STOCKS = {
    "BABA": {"name": "Alibaba Group",  "name_zh": "阿里巴巴", "bg": "images/stocks/BABA.png", "exchange": "NYSE", "currency": "USD"},
    "BIDU": {"name": "Baidu Inc.",     "name_zh": "百度",     "bg": "images/stocks/BIDU.png", "exchange": "NYSE", "currency": "USD"},
    "NIO":  {"name": "NIO Inc.",       "name_zh": "蔚来",     "bg": "images/stocks/NIO.png",  "exchange": "NYSE", "currency": "USD"},
    "JD":   {"name": "JD.com",         "name_zh": "京东",     "bg": "images/stocks/JD.png",   "exchange": "NYSE", "currency": "USD"},
    "BILI": {"name": "Bilibili Inc.",  "name_zh": "哔哩哔哩", "bg": "images/stocks/BILI.png", "exchange": "NYSE", "currency": "USD"},
}

LSE_STOCKS = {
    "HSBA.L": {"name": "HSBC Holdings",    "name_zh": "汇丰控股", "bg": "images/stocks/HSBA.L.png", "exchange": "LSE", "currency": "GBX"},
    "BP.L":   {"name": "BP plc",           "name_zh": "英国石油", "bg": "images/stocks/BP.L.png",   "exchange": "LSE", "currency": "GBX"},
    "ULVR.L": {"name": "Unilever plc",     "name_zh": "联合利华", "bg": "images/stocks/ULVR.L.png", "exchange": "LSE", "currency": "GBX"},
}

TSE_STOCKS = {
    "7203.T": {"name": "Toyota Motor Corp.",   "name_zh": "丰田汽车",   "bg": "images/stocks/7203.T.png", "exchange": "TSE", "currency": "JPY"},
    "6758.T": {"name": "Sony Group Corp.",     "name_zh": "索尼集团",   "bg": "images/stocks/6758.T.png", "exchange": "TSE", "currency": "JPY"},
    "9984.T": {"name": "SoftBank Group Corp.", "name_zh": "软银集团",   "bg": "images/stocks/9984.T.png", "exchange": "TSE", "currency": "JPY"},
}

REAL_STOCKS = {**ADR_STOCKS, **LSE_STOCKS, **TSE_STOCKS}
REAL_TICKERS = list(REAL_STOCKS.keys())

FX_TICKERS = {
    "USD": "USDCNY=X",
    "GBP": "GBPCNY=X",
    "JPY": "JPYCNY=X",
}
FX_FALLBACK_RATES = {
    "USD": 7.25,
    "GBP": 9.20,
    "JPY": 0.048,
}
FX_REFRESH_INTERVAL = 600

ETF_TICKER = "CNXF"
ETF_INFO = {
    "name":       "CCP National Index Fund",
    "name_zh":    "中华全国指数基金",
    "bg":         "images/stocks/ETF.png",
    "base_price": 50.0,
}

PENNY_STOCKS = {
    "XMNG": {"name": "Xian Mining Corp.",     "name_zh": "西安矿业",   "base_price": 0.85,  "daily_vol": 0.18},
    "DWJT": {"name": "Dongwei Jute Textiles", "name_zh": "东威黄麻纺", "base_price": 2.40,  "daily_vol": 0.22},
    "HQBC": {"name": "Huaqing Biocomponents", "name_zh": "华清生物",   "base_price": 0.33,  "daily_vol": 0.30},
    "RMKD": {"name": "Ren Mao Keratin Dev.",  "name_zh": "仁猫角蛋白", "base_price": 1.15,  "daily_vol": 0.25},
    "WSJZ": {"name": "Wushan Jian Zhu Co.",   "name_zh": "五山建筑",   "base_price": 4.20,  "daily_vol": 0.15},
}

TURBO_LEVERAGES = [2, 3, 5, 7, 10]
TURBOS_PER_DAY  = 12
TURBO_MIN_COST  = 100

PRICE_UPDATE_INTERVAL = 120

CIRCUIT_BREAKER_HALT_PCT  = 0.07
CIRCUIT_BREAKER_HALT_SECS = 900
CIRCUIT_BREAKER_DAILY_PCT = 0.20

PUMP_TRIGGER_PROB   = 0.00015
PUMP_DURATION_SECS  = 7200
PUMP_DRIFT_PER_TICK = 0.005
PUMP_CRASH_PCT      = 0.80

_YF_PERIOD_MAP = {
    "1D": ("1d",  "5m"),
    "5D": ("5d",  "15m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y",  "1d"),
}

_PERIOD_SECONDS = {
    "1D": 86400,
    "5D": 432000,
    "1M": 2592000,
    "3M": 7776000,
    "6M": 15552000,
    "1Y": 31536000,
}

ADR_TICKERS   = list(ADR_STOCKS.keys())
LSE_TICKERS   = list(LSE_STOCKS.keys())
TSE_TICKERS   = list(TSE_STOCKS.keys())
PENNY_TICKERS = list(PENNY_STOCKS.keys())
ALL_TICKERS   = ADR_TICKERS + LSE_TICKERS + TSE_TICKERS + [ETF_TICKER] + PENNY_TICKERS
