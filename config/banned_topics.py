import re

_PATTERNS = [
    r"tiananmen",
    r"tankman|(tiananmen|1989|china|protest).{0,60}tank\s*man|tank\s*man.{0,60}(tiananmen|1989|china|protest)",
    r"june\s*4(th)?.{0,40}(massacre|protest|crackdown|incident|tiananmen)|(massacre|protest|crackdown|incident|tiananmen).{0,40}june\s*4(th)?",
    r"1989\s*massacre",
    r"massacre\s*of\s*1989",
    r"taiwan\s*independen(ce|t)",
    r"free\s*taiwan",
    r"taiwan\s*is\s*(not\s*)?china",
    r"tibet\s*independen(ce|t)",
    r"free\s*tibet",
    r"uyghur\s*(genocide|concentration|camp|persec)",
    r"xinjiang\s*(camp|detention|genocide|atrocit)",
    r"falun\s*gong",
    r"falun\s*dafa",
    r"hong\s*kong\s*independen(ce|t)",
    r"liberate\s*hong\s*kong",
    r"ccp\s*(is\s*)?(evil|corrupt|lies|murderers?|criminals?)",
    r"down\s*with\s*(the\s*)?(ccp|china|xi)",
    r"xi\s*jinping\s*(is\s*)?(dictator|criminal|evil|pooh|corrupt)",
    r"winnie\s*the\s*pooh\s*(xi|jinping)",
    r"(china|chinese|ccp|uyghur|falun|prisoner|detain).{0,60}organ\s*harvest|organ\s*harvest.{0,60}(china|chinese|ccp|uyghur|falun|prisoner|detain)",
    r"social\s*credit\s*(is\s*)?(bad|evil|wrong|stupid|dystopia)",
    r"(tiananmen|1989|beijing|china|chinese).{0,60}massacre|massacre.{0,60}(tiananmen|1989|beijing|china|chinese)",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def contains_banned_topic(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED)


def get_banned_match(text: str) -> str | None:
    for p in _COMPILED:
        m = p.search(text)
        if m:
            return m.group(0)
    return None
