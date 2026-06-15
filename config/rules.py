STRUCTURAL_RULES = [
    {
        "type": "spam",
        "min_length": 10,
        "delta": -0.7,
        "reason": "repeated transmission",
    },
    {
        "type": "caps",
        "threshold": 0.8,
        "min_length": 16,
        "delta": -0.4,
        "reason": "disruptive formatting",
    },
]

SENTIMENT_SCALE = 0.30
SENTIMENT_NEUTRAL_THRESHOLD = 0.05
NEUTRAL_BONUS = 0.03

YUAN_PER_MESSAGE = 10

DAILY_MSG_SCORE_CAP = 8.0
DAILY_MSG_DIMINISHING_THRESHOLD = 25
DAILY_MSG_DIMINISHING_FACTOR = 0.25
