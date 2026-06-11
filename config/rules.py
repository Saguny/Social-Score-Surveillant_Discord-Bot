STRUCTURAL_RULES = [
    {
        "type": "spam",
        "delta": -1.0,
        "reason": "repeated transmission",
    },
    {
        "type": "caps",
        "threshold": 0.8,
        "min_length": 10,
        "delta": -0.2,
        "reason": "disruptive formatting",
    },
]

SENTIMENT_SCALE = 0.2
SENTIMENT_NEUTRAL_THRESHOLD = 0.05

YUAN_PER_MESSAGE = 1
