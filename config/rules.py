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

SENTIMENT_SCALE = 0.3
SENTIMENT_NEUTRAL_THRESHOLD = 0.05

YUAN_PER_MESSAGE = 10
