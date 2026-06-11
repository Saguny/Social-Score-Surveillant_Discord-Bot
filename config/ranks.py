RANKS = [
    {"name": "Enemy of the State",    "min": 600,  "max": 699},
    {"name": "Person of Interest",    "min": 700,  "max": 774},
    {"name": "Unremarkable Citizen",  "min": 775,  "max": 849},
    {"name": "Compliant Citizen",     "min": 850,  "max": 924},
    {"name": "Model Citizen",         "min": 925,  "max": 999},
    {"name": "Party Loyalist",        "min": 1000, "max": 1099},
    {"name": "Cadre Member",          "min": 1100, "max": 1199},
    {"name": "General Secretary",     "min": 1200, "max": 1300},
]

SCORE_FLOOR    = 600
SCORE_CEILING  = 1300
STARTING_SCORE = 750.0


def get_rank(score: float) -> dict:
    s = int(score)
    for rank in RANKS:
        if rank["min"] <= s <= rank["max"]:
            return rank
    return RANKS[-1] if score >= 1200 else RANKS[0]
