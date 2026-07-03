from config.shop import GACHA_UPGRADE_TIERS

CLAIM_WINDOW        = 60
ROLL_WINDOW         = 3600
BASE_ROLLS          = 10
MAX_CLAIMS_PER_HOUR = 1
MAX_STREAK_BONUS    = 4
HAREM_PAGE_SIZE     = 15
BROWSE_PAGE_SIZE    = 10
WISHLIST_MAX        = 10

WISHLIST_SPAWN_BASE  = 0.02
WISHLIST_SPAWN_RATES = [v / 100 for v in GACHA_UPGRADE_TIERS["gacha_spawn"]["values"]]
ROLL_BONUS_PER_TIER  = GACHA_UPGRADE_TIERS["gacha_rolls"]["values"]
WISHLIST_SLOT_TIERS  = GACHA_UPGRADE_TIERS["gacha_slots"]["values"]

FACTION_COLOR = {
    "reds":         0xA01414,
    "capitalists":  0x144696,
    "conquerors":   0x6E460F,
    "strongmen":    0x461450,
    "philosophers": 0x0F5A50,
    "icons":        0xC8860A,
    "wildcards":    0x505014,
}

FACTION_LABEL = {
    "reds":         "THE REDS",
    "capitalists":  "THE CAPITALISTS",
    "conquerors":   "THE CONQUERORS",
    "strongmen":    "THE STRONGMEN",
    "philosophers": "PHILOSOPHERS",
    "icons":        "ICONS",
    "wildcards":    "WILDCARDS",
}

RARITY_STARS = {
    "legendary": 5,
    "epic":      4,
    "rare":      3,
    "uncommon":  2,
    "common":    1,
}

RARITY_ORDER  = ["legendary", "epic", "rare", "uncommon", "common"]
FACTION_ORDER = list(FACTION_LABEL.keys())

RARITY_EMOJI = {
    "legendary": "🟡",
    "epic":      "🟣",
    "rare":      "🔵",
    "uncommon":  "🟢",
    "common":    "⚪",
}

DUPE_YUAN = {
    "legendary": 5000,
    "epic":      2000,
    "rare":      800,
    "uncommon":  300,
    "common":    100,
}

DUPE_COLOR = 0xFF3366
DUPE_EMOJI = "💴"

SUBMIT_URL = "https://off-by-one.digital/social-credit/submit"
