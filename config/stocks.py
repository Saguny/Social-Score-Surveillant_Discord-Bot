import math

ADR_STOCKS = {
    "BABA": {"name": "Alibaba Group",  "name_zh": "阿里巴巴", "bg": "images/stocks/BABA.png"},
    "BIDU": {"name": "Baidu Inc.",     "name_zh": "百度",     "bg": "images/stocks/BIDU.png"},
    "NIO":  {"name": "NIO Inc.",       "name_zh": "蔚来",     "bg": "images/stocks/NIO.png"},
    "JD":   {"name": "JD.com",         "name_zh": "京东",     "bg": "images/stocks/JD.png"},
    "BILI": {"name": "Bilibili Inc.",  "name_zh": "哔哩哔哩", "bg": "images/stocks/BILI.png"},
}

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
PENNY_TICKERS = list(PENNY_STOCKS.keys())
ALL_TICKERS   = ADR_TICKERS + [ETF_TICKER] + PENNY_TICKERS
