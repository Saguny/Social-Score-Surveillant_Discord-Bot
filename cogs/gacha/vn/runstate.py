"""
Run state for VN episodes.

These are load-bearing boundaries, not stylistic preferences. Each one is what
keeps some other part of the system simple; breaking one moves complexity
somewhere it does not belong.

1. Choice effects are the only state mutations. Scenes never carry effects, so
   re-entering a scene on resume or replay can never double-apply. Adding
   scene-entry effects means inventing fire-once/fire-every/fire-after-resume
   semantics and tracking which scenes already fired.
2. Routers only read state and pick a destination. They never mutate. If a
   branch needs a flag set, the choice that leads into it sets it.
3. Run variables affect routing, never rendering. The render cache is keyed
   (story_id, scene_id, party_ids) and is only sound while a scene is a pure
   function of those three. Dialogue reacting to earlier choices is a
   renderer/cache redesign, not a tweak here.
4. Router evaluation stays deliberately simple: an ordered list, first match
   wins, `next_scene` as fallback. Resist growing AND/OR/NOT, nesting, ranges,
   or variable-to-variable comparison — that turns the editor into a visual
   programming language. An episode needing complex logic should chain a second
   router instead.
5. Prefetch is an optimization and is allowed to miss routed branches. It has no
   run variables, so it cannot resolve a router; teaching it to would push
   run-state awareness into a rendering optimization.
6. `run_active` means currently executing. `completed_at` means historically
   finished. They are not interchangeable — `completed_at` is sticky, so it
   cannot distinguish a replay in progress from an episode cleared months ago.
"""
from __future__ import annotations

MAX_ROUTER_HOPS = 25

FEATURED_BONUS      = 2
FACTION_BONUS       = 2
FACTION_MIN_MEMBERS = 2

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a >  b,
    "<":  lambda a, b: a <  b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def apply_effects(run_vars: dict | None, effects: dict | None) -> dict:
    """New vars with effects applied. Booleans are set, numbers accumulate."""
    out = dict(run_vars or {})
    for key, val in (effects or {}).items():
        if isinstance(val, bool):
            out[key] = val
        elif isinstance(val, (int, float)):
            current = out.get(key)
            out[key] = (current if isinstance(current, (int, float)) and not isinstance(current, bool) else 0) + val
        else:
            out[key] = val
    return out


def _comparable(left, right):
    if isinstance(right, bool):
        return bool(left), right
    if isinstance(left, bool):
        return int(left), right
    return left, right


def check_condition(run_vars: dict | None, condition: dict) -> bool:
    op = _OPS.get(condition.get("op") or ">=")
    if op is None:
        return False
    left  = (run_vars or {}).get(condition.get("var"), 0)
    right = condition.get("value", 0)
    try:
        return bool(op(*_comparable(left, right)))
    except TypeError:
        return False


def route(scene: dict, run_vars: dict | None) -> str | None:
    """Where a router points, given the run state. First matching condition wins."""
    for condition in (scene.get("conditions") or []):
        target = condition.get("scene")
        if target and check_condition(run_vars, condition):
            return target
    return scene.get("next_scene")


async def resolve_scene(get_scene, story_id: str, scene_id: str, run_vars: dict | None):
    """
    Follow router scenes until a renderable one. Routers never render, so this
    is what every navigation path calls before handing a scene to the renderer.
    Returns None on a dead end, a missing scene, or a routing cycle.
    """
    seen: set[str] = set()
    current = scene_id

    for _ in range(MAX_ROUTER_HOPS):
        scene = await get_scene(story_id, current)
        if scene is None:
            return None
        if scene.get("scene_type") != "router":
            return scene
        if current in seen:
            return None
        seen.add(current)
        nxt = route(scene, run_vars)
        if not nxt:
            return None
        current = nxt

    return None


def choice_effects(choice: dict, passed: bool) -> dict:
    """Effects from taking a choice, merged with the branch-specific ones."""
    merged = dict(choice.get("effects") or {})
    branch = choice.get("pass_effects") if passed else choice.get("fail_effects")
    for key, val in (branch or {}).items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            merged[key] = val
        else:
            base = merged.get(key)
            merged[key] = (base if isinstance(base, (int, float)) and not isinstance(base, bool) else 0) + val
    return merged


def party_bonuses(story: dict, party_chars: list, choice: dict | None = None) -> tuple[int, list[str]]:
    """
    Roll bonuses earned by party composition: the story's featured character
    being present, and enough of the party sharing the relevant faction.
    """
    bonus  = 0
    labels: list[str] = []

    featured_id = story.get("featured_char_id")
    if featured_id:
        match = next(
            (c for c in party_chars if c and c.get("character_id") == featured_id), None
        )
        if match:
            bonus += FEATURED_BONUS
            labels.append(f"{match.get('name', 'featured')} +{FEATURED_BONUS}")

    faction = (choice or {}).get("faction") or story.get("faction")
    if faction:
        aligned = sum(1 for c in party_chars if c and c.get("faction") == faction)
        if aligned >= FACTION_MIN_MEMBERS:
            bonus += FACTION_BONUS
            labels.append(f"{faction} x{aligned} +{FACTION_BONUS}")

    return bonus, labels
