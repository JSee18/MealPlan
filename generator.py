"""Picks which recipes best hit a client's daily calorie/macro targets.

v1 scope: a single day's meals + snacks, chosen by brute-force search over
every valid combination (recipe count is small enough that this is fast and
exact — no need for a solver yet). Preferences are a hard filter applied
before scoring, never traded off against macro fit.
"""

import itertools
import json

MEAL_SLOTS_BY_COUNT = {
    1: ["dinner"],
    2: ["lunch", "dinner"],
    3: ["breakfast", "lunch", "dinner"],
}

MEAL_TYPE_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3, "side": 4}


def sort_meals_with_paired_sides(combo):
    """Orders a day's meals so a side sits right after the meal it's paired with
    (e.g. Extra Banana appears directly under Overnight Oats rather than floating
    at the end), instead of the raw meals-then-snacks-then-sides order they were
    picked in.
    """
    def key(item):
        _, r = item
        meal_type = r["paired_with"] if r["meal_type"] == "side" else r["meal_type"]
        is_side = r["meal_type"] == "side"
        return (MEAL_TYPE_ORDER.get(meal_type, 99), is_side)

    return sorted(combo, key=key)


def get_client(conn, client_id):
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    cols = [d[0] for d in conn.execute("SELECT * FROM clients LIMIT 0").description]
    return dict(zip(cols, row))


def get_recipe_nutrition(conn):
    """Returns {recipe_id: {"name", "meal_type", "kcal", "protein", "carbs",
    "fat", "fibre", "dietary_tags", "batch_cook_suitable", "side_pairs_with",
    "is_protein_topper", "no_added_protein_needed", "requires_blender",
    "ingredient_names"}} — per-serving nutrition for every recipe."""
    recipes = {}
    for (recipe_id, name, meal_type, base_servings, dietary_tags, batch_cook_suitable,
         side_pairs_with, is_protein_topper, no_added_protein_needed, requires_blender) in conn.execute(
        """SELECT id, name, meal_type, base_servings, dietary_tags, batch_cook_suitable,
                  side_pairs_with, is_protein_topper, no_added_protein_needed, requires_blender
           FROM recipes"""
    ):
        totals = conn.execute(
            """
            SELECT SUM(i.calories_per_100g * ri.quantity_g / 100.0),
                   SUM(i.protein_per_100g * ri.quantity_g / 100.0),
                   SUM(i.carbs_per_100g * ri.quantity_g / 100.0),
                   SUM(i.fat_per_100g * ri.quantity_g / 100.0),
                   SUM(i.fibre_per_100g * ri.quantity_g / 100.0)
            FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = ?
            """,
            (recipe_id,),
        ).fetchone()
        kcal, protein, carbs, fat, fibre = totals
        ingredient_names = {
            row[0] for row in conn.execute(
                "SELECT i.name FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id WHERE ri.recipe_id = ?",
                (recipe_id,),
            )
        }
        recipes[recipe_id] = {
            "name": name,
            "meal_type": meal_type,
            "kcal": kcal / base_servings,
            "protein": protein / base_servings,
            "carbs": carbs / base_servings,
            "fat": fat / base_servings,
            "fibre": (fibre or 0) / base_servings,
            "dietary_tags": json.loads(dietary_tags),
            "batch_cook_suitable": bool(batch_cook_suitable),
            "side_pairs_with": json.loads(side_pairs_with) if side_pairs_with else [],
            "is_protein_topper": bool(is_protein_topper),
            "no_added_protein_needed": bool(no_added_protein_needed),
            "requires_blender": bool(requires_blender),
            "ingredient_names": ingredient_names,
        }
    return recipes


def passes_preferences(recipe, preferences):
    """suitable_for: client must follow ALL listed diet styles, so the recipe
    must be suitable for each one. exclusions: recipe is rejected if it
    contains OR may contain any excluded allergen (safe/conservative default).
    disliked_ingredients: a separate, non-allergen preference (e.g. "doesn't like
    bananas") - rejected if the recipe uses that exact ingredient, regardless of
    quantity - a dislike doesn't have a safe threshold the way trace allergens
    might, so any amount is enough to exclude the recipe.
    """
    tags = recipe["dietary_tags"]
    for style in preferences.get("suitable_for", []):
        if style not in tags["suitable_for"]:
            return False
    excluded = set(preferences.get("exclusions", []))
    if excluded & set(tags["allergy_info"]["contains"]):
        return False
    if excluded & set(tags["allergy_info"]["may_contain"]):
        return False
    disliked = set(preferences.get("disliked_ingredients", []))
    if disliked & recipe["ingredient_names"]:
        return False
    return True


def score_combination(recipes_in_combo, targets):
    """Sum of relative absolute deviation across kcal/protein/carbs/fat, plus a
    fibre penalty — lower is better. Uniform weighting for v1; worth revisiting
    once this is validated against real client plans.

    Fibre is a floor, not a ceiling (25g+ is fine, there's no official upper
    limit) - see fibre being shown with no ceiling on the UI. But with nothing at
    all discouraging it in the score, the sides search (best_sides_for) had no
    reason not to pile on fibre-dense veg past any sensible point purely because
    it also helped close a calorie/carb gap - some plans came out at ~50g, double
    the ~25g target. Penalizing only the amount *above* target keeps the "no
    ceiling" intent (hitting the target costs nothing) while still discouraging
    genuinely excessive amounts.
    """
    totals = {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0, "fibre": 0}
    for r in recipes_in_combo:
        for k in totals:
            totals[k] += r[k]

    score = 0
    for k, target_key in [("kcal", "calorie_target"), ("protein", "protein_g"),
                           ("carbs", "carbs_g"), ("fat", "fat_g")]:
        target = targets[target_key]
        score += abs(totals[k] - target) / target

    fibre_target = targets["fibre_g"]
    score += max(0, totals["fibre"] - fibre_target) / fibre_target
    return score, totals


def compute_slot_targets(targets, num_slots):
    """Splits the day's kcal/protein/carbs/fat targets evenly across every meal and
    snack occurrence (num_slots = count of meal_slots + snacks_per_day), so each one
    is expected to carry a fair, even share of the day rather than only the day's
    total being checked. Without this, a 550kcal breakfast paired with a 250kcal
    lunch scored exactly the same as two well-matched 400kcal meals, as long as the
    day's aggregate landed close to target - nothing discouraged lopsided days.
    Fibre is deliberately left out: it's a daily-total floor/ceiling concern (see
    score_combination), not something that makes sense to split evenly per meal.
    """
    return {
        "calorie_target": targets["calorie_target"] / num_slots,
        "protein_g": targets["protein_g"] / num_slots,
        "carbs_g": targets["carbs_g"] / num_slots,
        "fat_g": targets["fat_g"] / num_slots,
    }


def score_recipe_against_slot(recipe, slot_target):
    """Relative absolute deviation of one recipe against its even per-slot share of
    the day's target - same shape as score_combination's day-level scoring, just
    applied to a single meal instead of the whole day's totals."""
    score = 0
    for k, target_key in [("kcal", "calorie_target"), ("protein", "protein_g"),
                           ("carbs", "carbs_g"), ("fat", "fat_g")]:
        score += abs(recipe[k] - slot_target[target_key]) / slot_target[target_key]
    return score


def get_fibre_target(conn):
    """EFSA adequate intake for fibre, adults 18+ (see nutrient_targets)."""
    row = conn.execute(
        "SELECT value FROM nutrient_targets WHERE nutrient = 'fibre' AND age_min <= 18 AND age_max >= 18 LIMIT 1"
    ).fetchone()
    return row[0] if row else 25.0


MAX_SIDES_PER_DAY = 6  # up to ~1-2 per meal/snack slot - still bounded, not "8 side dishes"
MAX_SIDES_PER_MEAL = 2  # e.g. a banana + yogurt with breakfast is fine; 3+ starts looking odd

REDUNDANT_PAIRING_KEYWORDS = ["salad", "bread"]  # e.g. don't pair Side Salad with Salmon and Pasta
# Salad, or two of the Multiseed Bread variants with each other in the same slot


def is_redundant_pairing(side_name, main_recipes):
    """Avoids nonsensical pairings like Side Salad next to a dish that's already a
    salad (e.g. Salmon and Pasta Salad) - matched by a shared category keyword in
    the recipe names rather than a hardcoded list of specific dish pairs, so it
    applies to any current or future recipe without per-pair maintenance.
    """
    side_lower = side_name.lower()
    for keyword in REDUNDANT_PAIRING_KEYWORDS:
        if keyword in side_lower and any(keyword in r["name"].lower() for r in main_recipes):
            return True
    return False


def is_unwanted_pairing(side, main_recipes):
    """True if `side` shouldn't be offered alongside this slot's main recipe(s) -
    either a redundant category (see is_redundant_pairing) or a protein topper
    (e.g. Grilled Chicken Breast) being offered to a main that's tagged
    no_added_protein_needed (already built around its own meat/fish protein, e.g.
    Rainbow Salad or Spicy Pot Noodle already contain chicken).
    """
    if is_redundant_pairing(side["name"], main_recipes):
        return True
    if side["is_protein_topper"] and any(r["no_added_protein_needed"] for r in main_recipes):
        return True
    return False


def best_sides_for(base_combo, side_options, available_slots, targets, max_sides, num_slots, max_per_slot=MAX_SIDES_PER_MEAL):
    """Given an already-chosen meal+snack combo, separately searches for the best
    sides to add on top of it, slot by slot (in available_slots order - typically
    breakfast, lunch, dinner, snack), each slot taking 0..max_per_slot from only
    the sides tagged compatible with it (recipes.side_pairs_with).

    Each slot's sides are picked to bring THAT slot's own total (its base recipe(s)
    plus whatever's already been added to it) closer to its fair, even share of the
    day - not to close the day's aggregate gap. Using the day aggregate here meant
    breakfast, always processed first, soaked up sides until the day *total* looked
    close enough, even while lunch/dinner sat well under their own fair share (e.g.
    Salmon and Pasta Salad at 358kcal, or Spaghetti Bolognese on a day short on
    calories) and so never got a veg side or a salad even though they needed one
    more than breakfast did. A day-level fibre check still runs alongside this, so
    the "no ceiling below target, penalise well above it" fibre behaviour is
    unchanged (see score_combination) - it's only the kcal/protein/carbs/fat
    decision that's now per-slot instead of day-aggregate.

    The per-slot cap has to be enforced here, during selection, not as a relabeling
    pass afterwards: several sides (e.g. Rice Cakes, Dark Chocolate) are tagged for
    snack ONLY, so if the search picks 4 of them, there is no other slot to move the
    extras to - a later "balance the labels" pass can't fix a selection that already
    overloaded one slot. Processing slot by slot and removing each chosen side from
    the pool as it's used prevents that at the source, and also means a side already
    used for breakfast can't separately be picked again for snack.

    This is a second stage rather than folded into the main meal/snack search (see
    the module docstring's brute-force-is-fine-for-v1 rationale): trying every side
    combination against every meal combination multiplies the two search spaces
    together and gets slow fast, whereas picking the best meal combo first and only
    then optimizing sides against it is additive instead of multiplicative - a
    side's contribution to the score doesn't depend on which meal combo was chosen,
    so this gives the same practical result far more cheaply. Sides are similarly
    greedy slot-by-slot rather than jointly optimized across slots, trading a fully
    global optimum for tractability - consistent with the same tradeoff already
    documented on generate_weekly_plan's day-by-day allocation.
    """
    base_recipes = [r for _, r in base_combo]
    slot_target = compute_slot_targets(targets, num_slots)
    chosen = []
    pool = list(side_options)
    total_chosen = 0

    for slot in available_slots:
        room = min(max_per_slot, max_sides - total_chosen)
        slot_recipes = [r for rid, r in base_combo if r["meal_type"] == slot]
        candidates = [
            (rid, r) for rid, r in pool
            if slot in r["side_pairs_with"] and not is_unwanted_pairing(r, slot_recipes)
        ]
        if room <= 0 or not candidates:
            continue

        # A slot can hold more than one recipe (multiple snacks in a day), so its
        # fair share scales with how many of the day's meals actually landed there.
        bucket_target = {k: v * (len(slot_recipes) or 1) for k, v in slot_target.items()}
        already_for_slot = [r for _, r in chosen if r["paired_with"] == slot]

        best_local_score, best_pick = None, ()
        for k in range(room + 1):
            for combo in itertools.combinations(candidates, k):
                combo_recipes = [r for _, r in combo]
                if any(
                    is_redundant_pairing(combo_recipes[i]["name"], [combo_recipes[j]])
                    for i in range(len(combo_recipes)) for j in range(i + 1, len(combo_recipes))
                ):
                    continue
                trial_slot_recipes = slot_recipes + already_for_slot + combo_recipes
                slot_totals = {
                    "kcal": sum(r["kcal"] for r in trial_slot_recipes),
                    "protein": sum(r["protein"] for r in trial_slot_recipes),
                    "carbs": sum(r["carbs"] for r in trial_slot_recipes),
                    "fat": sum(r["fat"] for r in trial_slot_recipes),
                }
                evenness = score_recipe_against_slot(slot_totals, bucket_target)

                day_recipes = base_recipes + [r for _, r in chosen] + combo_recipes
                _, day_totals = score_combination(day_recipes, targets)
                fibre_penalty = max(0, day_totals["fibre"] - targets["fibre_g"]) / targets["fibre_g"]
                ingredient_penalty = INGREDIENT_PREFERENCE_PENALTY if any(
                    r["ingredient_names"] & PENALIZED_INGREDIENTS for r in combo_recipes
                ) else 0

                score = evenness + fibre_penalty + ingredient_penalty
                if best_local_score is None or score < best_local_score:
                    best_local_score, best_pick = score, combo

        for rid, r in best_pick:
            chosen.append((rid, {**r, "paired_with": slot}))
            pool = [(i, rr) for i, rr in pool if i != rid]
            total_chosen += 1

    final_score, final_totals = score_combination(base_recipes + [r for _, r in chosen], targets)
    return final_score, chosen, final_totals


def generate_daily_plan(conn, client_id):
    client = get_client(conn, client_id)
    preferences = json.loads(client["preferences"])
    macros = json.loads(client["macro_targets"])
    targets = {
        "calorie_target": client["calorie_target"],
        "protein_g": macros["protein_g"],
        "carbs_g": macros["carbs_g"],
        "fat_g": macros["fat_g"],
        "fibre_g": get_fibre_target(conn),
    }

    all_recipes = get_recipe_nutrition(conn)
    eligible = {
        rid: r for rid, r in all_recipes.items()
        if passes_preferences(r, preferences) and (client["has_blender"] or not r["requires_blender"])
    }

    meal_slots = MEAL_SLOTS_BY_COUNT.get(client["meals_per_day"])
    if meal_slots is None:
        raise ValueError(
            f"meals_per_day={client['meals_per_day']} isn't supported yet "
            f"(only 1-3 mapped to slot types) - known v1 limitation."
        )

    by_meal_type = {}
    for meal_type in set(meal_slots) | {"snack"}:
        options = [(rid, r) for rid, r in eligible.items() if r["meal_type"] == meal_type]
        if not options:
            raise ValueError(f"No eligible recipes for meal_type='{meal_type}' after applying preferences.")
        by_meal_type[meal_type] = options

    snack_options = by_meal_type["snack"]
    snacks_per_day = min(client["snacks_per_day"], len(snack_options))

    # Sides (extra veg/fruit/etc.) are optional and uncapped - unlike mains, there's
    # nothing unrealistic about a client having a banana or a side salad most days, so
    # they aren't tracked through the batch/repeat-cap machinery below. Whether any get
    # used at all falls out of the scoring: a combo with sides only wins if it's a
    # closer fit than the same combo without them.
    side_options = [(rid, r) for rid, r in eligible.items() if r["meal_type"] == "side"]
    max_sides = min(MAX_SIDES_PER_DAY, len(side_options))
    available_slots = list(meal_slots) + (["snack"] if snacks_per_day > 0 else [])

    num_slots = len(meal_slots) + snacks_per_day
    slot_target = compute_slot_targets(targets, num_slots)

    best_score, best_combo, best_totals = None, None, None
    meal_option_lists = [by_meal_type[mt] for mt in meal_slots]
    for meal_choice in itertools.product(*meal_option_lists):
        for snack_choice in itertools.combinations(snack_options, snacks_per_day):
            combo = list(meal_choice) + list(snack_choice)
            _, totals = score_combination([r for _, r in combo], targets)
            evenness = sum(score_recipe_against_slot(r, slot_target) for _, r in combo)
            fibre_penalty = max(0, totals["fibre"] - targets["fibre_g"]) / targets["fibre_g"]
            score = evenness + fibre_penalty
            if best_score is None or score < best_score:
                best_score, best_combo, best_totals = score, combo, totals

    best_score, best_sides, best_totals = best_sides_for(
        best_combo, side_options, available_slots, targets, max_sides, num_slots
    )
    best_combo = sort_meals_with_paired_sides(best_combo + best_sides)

    return {
        "client_name": client["name"],
        "targets": targets,
        "totals": best_totals,
        "score": best_score,
        "meals": [{"recipe_id": rid, **r} for rid, r in best_combo],
    }


DEFAULT_BATCH_CAP = 3  # a batch-cooked recipe should be eaten across at most this many days
DAYS_IN_WEEK = 7
MAX_DISTINCT_RECIPES_PER_WEEK = 3  # cap on variety per meal type (breakfast/lunch/dinner/snack)

# A recipe/side using one of these is scored as a slightly worse fit than it actually
# is, whenever it's competing against something that doesn't - Jemma: prefer the
# branded/fortified products already established elsewhere (Yoplait Skyr, Avonmore
# Super Milk) and whole eggs (also lets the shopping list show "5 eggs" instead of a
# weight) over generic or duplicate alternatives, so the shopping list doesn't end up
# asking for two products doing the same job. Large enough to only lose the tie-break
# when no non-penalized option can fill the slot - never an outright ban.
PENALIZED_INGREDIENTS = {
    "Eggs, chicken, white, raw",
    "Yogurt, low fat, plain (approx. for low-fat Greek)",
    "Milk, whole, 3.5% fat (National Dairy Council, branded, real label)",
}
INGREDIENT_PREFERENCE_PENALTY = 2.0


def score_with_ingredient_preference(recipe, slot_target):
    score = score_recipe_against_slot(recipe, slot_target)
    if recipe["ingredient_names"] & PENALIZED_INGREDIENTS:
        score += INGREDIENT_PREFERENCE_PENALTY
    return score


# Side "products" that compete for the same role, where only one should be bought per
# week (e.g. Babybel vs Light Babybel) - each inner list is one product's recipe(s)
# (portion-size siblings, kept together), each outer list is the family of products
# competing for that one role. Unlike restrict_variety (per meal-slot-tag, reverted
# for sides - see 17655ba), this is scoped to specific known duplicates, so it can't
# accidentally let one crowded category (bread toppings) crowd out an unrelated one
# (veg sides).
SIDE_PRODUCT_FAMILIES = [
    [
        ["Protein Shake"],
        ["Protein Shake (with Milk)"],
        ["Protein Shake (with Light Milk)"],
    ],
    [
        ["Multiseed Bread with Babybel (1 Slice)", "Multiseed Bread with Babybel (2 Slices)"],
        ["Multiseed Bread with Light Babybel (1 Slice)", "Multiseed Bread with Light Babybel (2 Slices)"],
    ],
    [
        ["Multiseed Bread with Light Philadelphia (1 Slice)", "Multiseed Bread with Light Philadelphia (2 Slices)"],
        ["Multiseed Bread with Original Philadelphia (1 Slice)", "Multiseed Bread with Original Philadelphia (2 Slices)"],
    ],
    [
        ["Multiseed Bread with Butter (1 Slice)", "Multiseed Bread with Butter (2 Slices)"],
        ["Multiseed Bread with Flora (1 Slice)", "Multiseed Bread with Flora (2 Slices)"],
    ],
]


def restrict_product_families(side_options, slot_target, families=SIDE_PRODUCT_FAMILIES):
    """Keeps at most one product per family in SIDE_PRODUCT_FAMILIES this week (e.g.
    only Babybel OR Light Babybel, not both), rather than letting each get chosen
    independently on different days just because it happened to be a good macro fit
    that day - Jemma: two Babybel types, two protein powders, three milks in one
    shopping list "let's keep to 1 type per week so save the client [money/hassle]".

    Whichever product scores best (its closest-fitting recipe vs. the slot's fair
    share) wins the family; all of its portion-size siblings stay available (e.g.
    both the 1-slice and 2-slice Babybel option survive together), so this only
    removes cross-product duplication, not the within-product portion flexibility
    that closes calorie gaps.
    """
    by_name = {r["name"]: (rid, r) for rid, r in side_options}
    drop_names = set()
    for products in families:
        present = [[name for name in product if name in by_name] for product in products]
        present = [p for p in present if p]
        if len(present) <= 1:
            continue
        winner = min(present, key=lambda product: min(score_with_ingredient_preference(by_name[n][1], slot_target) for n in product))
        for product in present:
            if product is not winner:
                drop_names.update(product)
    return [(rid, r) for rid, r in side_options if r["name"] not in drop_names]


def restrict_variety(options, slot_target, max_recipes=MAX_DISTINCT_RECIPES_PER_WEEK):
    """Limits how many distinct recipes are eligible for one meal type this week
    to max_recipes, keeping whichever are the closest individual fits to the
    slot's fair share of the day's target. Once restricted, compute_even_caps
    spreads DAYS_IN_WEEK across just these few (e.g. 3 recipes -> roughly 3/2/2
    days each), so a client isn't juggling a different recipe practically every
    day - a handful reused across the week, simpler to shop and prep for.
    """
    if len(options) <= max_recipes:
        return options
    ranked = sorted(options, key=lambda pair: score_with_ingredient_preference(pair[1], slot_target))
    return ranked[:max_recipes]


def compute_even_caps(options, days_needed):
    """Splits days_needed as evenly as possible across the given recipes (e.g. 7
    days over 3 recipes -> 3/2/2), ignoring batch_cook_suitable entirely.

    This is deliberately different from compute_repeat_caps: that function caps
    non-batch recipes at 1 use/week on the assumption variety is otherwise
    unbounded, so a "fresh only" recipe shouldn't be repeated as if it were
    secretly batch-cooked. Once restrict_variety has already cut a meal type
    down to a handful of recipes, repetition is the explicit intent regardless
    of batch status - re-cooking a non-batch recipe fresh on 2-3 different days
    doesn't break its "never held over as leftovers" premise the way using it
    3 days from one cook would.
    """
    n = len(options)
    base, extra = divmod(days_needed, n)
    return {rid: base + (1 if i < extra else 0) for i, (rid, _) in enumerate(options)}


def compute_repeat_caps(options, slots_needed):
    """How many of the DAYS_IN_WEEK slots each recipe may fill this week.

    Non-batch-suitable recipes are capped at 1 (fresh only, never held over
    as leftovers). Batch-suitable recipes default to DEFAULT_BATCH_CAP, but
    if there simply aren't enough distinct recipes to cover every slot at
    that cap, it's relaxed — evenly, and only as far as necessary — so a
    full week can still be produced. Returns (caps: {recipe_id: int}, notes: [str])
    describing any relaxation, and raises ValueError if even a fully relaxed
    week (every recipe used every day) can't cover the need.
    """
    caps = {}
    notes = []
    fresh = [rid for rid, r in options if not r["batch_cook_suitable"]]
    batch = [rid for rid, r in options if r["batch_cook_suitable"]]

    for rid in fresh:
        caps[rid] = 1
    fresh_capacity = len(fresh)

    if batch:
        capacity_at_default = fresh_capacity + len(batch) * DEFAULT_BATCH_CAP
        if capacity_at_default >= slots_needed:
            for rid in batch:
                caps[rid] = DEFAULT_BATCH_CAP
        else:
            needed_from_batch = slots_needed - fresh_capacity
            relaxed_cap = -(-needed_from_batch // len(batch))  # ceil division
            relaxed_cap = min(relaxed_cap, DAYS_IN_WEEK)
            for rid in batch:
                caps[rid] = relaxed_cap
            meal_type = options[0][1]["meal_type"]
            notes.append(
                f"{meal_type}: only {len(batch)} batch-suitable + {fresh_capacity} fresh recipe(s) "
                f"available for {slots_needed} slots this week - repeat cap relaxed from "
                f"{DEFAULT_BATCH_CAP} to {relaxed_cap} days per recipe to fill the week. "
                f"Adding more {meal_type} recipes would let this tighten back down."
            )

    total_capacity = sum(caps.values())
    if total_capacity < slots_needed:
        meal_type = options[0][1]["meal_type"] if options else "unknown"
        raise ValueError(
            f"Can't fill {slots_needed} {meal_type} slots this week even at maximum repeats - "
            f"only {total_capacity} slots available from {len(options)} eligible recipe(s). "
            f"Needs more {meal_type} recipes in the database."
        )
    return caps, notes


def generate_weekly_plan(conn, client_id):
    """Same day-by-day macro-fit logic as generate_daily_plan, extended across
    7 days with a per-recipe repeat cap (see compute_repeat_caps). Allocation
    is greedy day-by-day: each day takes the best combo still available given
    what prior days have used.

    Tried reordering which day gets which combo (rank-based round-robin) to
    avoid quality declining toward day 7 — it didn't help. The number of
    well-fitting combos is fixed by how many recipes exist; reordering only
    relabels which day number gets a good vs. a poor result, it can't raise
    what's achievable. The real fix for days landing far from target is more
    recipes (see compute_repeat_caps' relaxation notes for exactly which meal
    types are thin), not smarter allocation.
    """
    client = get_client(conn, client_id)
    preferences = json.loads(client["preferences"])
    macros = json.loads(client["macro_targets"])
    targets = {
        "calorie_target": client["calorie_target"],
        "protein_g": macros["protein_g"],
        "carbs_g": macros["carbs_g"],
        "fat_g": macros["fat_g"],
        "fibre_g": get_fibre_target(conn),
    }

    all_recipes = get_recipe_nutrition(conn)
    eligible = {
        rid: r for rid, r in all_recipes.items()
        if passes_preferences(r, preferences) and (client["has_blender"] or not r["requires_blender"])
    }

    meal_slots = MEAL_SLOTS_BY_COUNT.get(client["meals_per_day"])
    if meal_slots is None:
        raise ValueError(
            f"meals_per_day={client['meals_per_day']} isn't supported yet "
            f"(only 1-3 mapped to slot types) - known v1 limitation."
        )

    by_meal_type = {}
    for meal_type in set(meal_slots) | {"snack"}:
        options = [(rid, r) for rid, r in eligible.items() if r["meal_type"] == meal_type]
        if not options:
            raise ValueError(f"No eligible recipes for meal_type='{meal_type}' after applying preferences.")
        by_meal_type[meal_type] = options

    snacks_per_day = min(client["snacks_per_day"], len(by_meal_type["snack"]))

    # Sides are optional and deliberately excluded from the repeat-cap machinery below
    # (see generate_daily_plan) - a client can reasonably have a banana or side salad
    # most days, so they're available every day rather than being rationed like mains.
    side_options = [(rid, r) for rid, r in eligible.items() if r["meal_type"] == "side"]
    available_slots = list(meal_slots) + (["snack"] if snacks_per_day > 0 else [])

    num_slots = len(meal_slots) + snacks_per_day
    slot_target = compute_slot_targets(targets, num_slots)

    # Restrict each meal type to a handful of recipes before capping repeats, rather
    # than letting the day-by-day search freely draw from every eligible recipe - see
    # restrict_variety()/compute_even_caps() for why (Jemma: "stick to 3 options for
    # each per week").
    #
    # Sides are deliberately NOT restricted the same blanket way as mains. Tried it
    # (per-meal-type-tag) and reverted: with 14 near-identical "Multiseed Bread with X"
    # variants all tagged lunch/dinner, they dominated every top-N ranking and crowded
    # out the veg sides (Roasted Carrots, Steamed Broccoli, etc.) that were actually
    # doing the calorie-gap-closing work - e.g. one test client's day 4 regressed from
    # -37kcal back to -248kcal, while the shopping list barely shrank (92 -> 88 items).
    # restrict_product_families() instead targets only the specific known duplicates
    # (two Babybel types, two protein powders, etc. - Jemma: "keep to 1 type per
    # week") without touching unrelated categories like veg.
    for meal_type in meal_slots:
        by_meal_type[meal_type] = restrict_variety(by_meal_type[meal_type], slot_target)
    snack_options = restrict_variety(by_meal_type["snack"], slot_target)
    side_options = restrict_product_families(side_options, slot_target)
    max_sides = min(MAX_SIDES_PER_DAY, len(side_options))

    caps, notes = {}, []
    for meal_type in meal_slots:
        caps.update(compute_even_caps(by_meal_type[meal_type], DAYS_IN_WEEK))
    caps.update(compute_even_caps(snack_options, snacks_per_day * DAYS_IN_WEEK))

    usage = {rid: 0 for rid in caps}
    days = []
    for day_num in range(1, DAYS_IN_WEEK + 1):
        # Falls back to the full (already variety-restricted) pool for a slot if every
        # option is at capacity today - compute_even_caps' split has zero slack (it
        # sums to exactly DAYS_IN_WEEK), so a greedy day-by-day allocation can otherwise
        # exhaust every recipe for a slot before all 7 days are filled, especially with
        # snacks_per_day > 1 needing multiple *distinct* recipes on the same day from
        # only a handful available for the whole week. Falling back trades a slightly
        # uneven split for guaranteeing every day can still be filled.
        day_meal_options = {}
        for mt in meal_slots:
            opts = [(rid, r) for rid, r in by_meal_type[mt] if usage[rid] < caps[rid]]
            day_meal_options[mt] = opts or by_meal_type[mt]

        day_snack_options = [(rid, r) for rid, r in snack_options if usage[rid] < caps[rid]]
        if len(day_snack_options) < snacks_per_day:
            day_snack_options = snack_options

        best_score, best_combo, best_totals = None, None, None
        meal_option_lists = [day_meal_options[mt] for mt in meal_slots]
        for meal_choice in itertools.product(*meal_option_lists):
            for snack_choice in itertools.combinations(day_snack_options, snacks_per_day):
                combo = list(meal_choice) + list(snack_choice)
                _, totals = score_combination([r for _, r in combo], targets)
                evenness = sum(score_recipe_against_slot(r, slot_target) for _, r in combo)
                fibre_penalty = max(0, totals["fibre"] - targets["fibre_g"]) / targets["fibre_g"]
                score = evenness + fibre_penalty
                if best_score is None or score < best_score:
                    best_score, best_combo, best_totals = score, combo, totals

        best_score, best_sides, best_totals = best_sides_for(
            best_combo, side_options, available_slots, targets, max_sides, num_slots
        )

        for rid, _ in best_combo + best_sides:
            if rid in usage:
                usage[rid] += 1

        best_combo = sort_meals_with_paired_sides(best_combo + best_sides)

        days.append({
            "day": day_num,
            "totals": best_totals,
            "score": best_score,
            "meals": [{"recipe_id": rid, **r} for rid, r in best_combo],
        })

    return {
        "client_name": client["name"],
        "targets": targets,
        "days": days,
        "notes": notes,
    }


def generate_shopping_list(conn, weekly_plan):
    """Aggregates ingredient quantities across a full weekly plan.

    Batch cooking is accounted for: if a recipe is used more times in the
    week than its base_servings covers in one batch, it needs to be cooked
    multiple times (times_to_cook = ceil(times_used / base_servings)), and
    the shopping list buys that many batches' worth of ingredients — not
    one batch per use. This is what makes batch cooking actually reduce
    the shopping list rather than just relabeling the same total.

    Ingredients with a shopping_unit_size_g (e.g. eggs, bananas, stock cubes)
    are displayed as a rounded-up unit count ("3 eggs") instead of a weight —
    rounded up rather than to nearest, since a shopper can't buy a fraction of
    an egg and it's better to have a little extra than to come up short.
    Ingredients flagged exclude_from_shopping_list (currently just Water) are
    dropped entirely — they're used in recipes but nobody buys them.
    """
    usage_count = {}
    is_side_recipe = {}
    for day in weekly_plan["days"]:
        for meal in day["meals"]:
            usage_count[meal["recipe_id"]] = usage_count.get(meal["recipe_id"], 0) + 1
            is_side_recipe[meal["recipe_id"]] = meal["meal_type"] == "side"

    ingredient_totals = {}  # ingredient_id -> {"name", "category", "quantity_g", "unit_size_g", "unit_name", "used_by_main"}
    recipes_used = []
    for recipe_id, times_used in usage_count.items():
        name, base_servings = conn.execute(
            "SELECT name, base_servings FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        times_to_cook = -(-times_used // base_servings)  # ceil division
        recipes_used.append({
            "recipe_id": recipe_id, "name": name, "times_used": times_used,
            "base_servings": base_servings, "times_to_cook": times_to_cook,
        })

        for ing_id, ing_name, ing_category, qty_g, unit_size_g, unit_name, excluded in conn.execute(
            """
            SELECT i.id, i.name, i.category, ri.quantity_g,
                   i.shopping_unit_size_g, i.shopping_unit_name, i.exclude_from_shopping_list
            FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = ?
            """,
            (recipe_id,),
        ):
            if excluded:
                continue
            if ing_id not in ingredient_totals:
                ingredient_totals[ing_id] = {
                    "name": ing_name, "category": ing_category or "Other", "quantity_g": 0,
                    "unit_size_g": unit_size_g, "unit_name": unit_name, "used_by_main": False,
                }
            ingredient_totals[ing_id]["quantity_g"] += qty_g * times_to_cook
            if not is_side_recipe[recipe_id]:
                ingredient_totals[ing_id]["used_by_main"] = True

    for item in ingredient_totals.values():
        if item["unit_size_g"]:
            count = -(-item["quantity_g"] // item["unit_size_g"])  # ceil division
            plural = "" if count == 1 else "s"
            item["display"] = f"{count:.0f} {item['unit_name']}{plural}"
        elif item["quantity_g"] >= 1000:
            item["display"] = f"{item['quantity_g'] / 1000:.2f} kg"
        else:
            item["display"] = f"{item['quantity_g']:.0f} g"

    items = sorted(ingredient_totals.values(), key=lambda x: x["name"])

    def group_by_category(items_subset):
        by_category = {}
        for item in items_subset:
            by_category.setdefault(item["category"], []).append(item)
        return [
            {"category": cat, "items": by_category[cat]}
            for cat in sorted(by_category, key=lambda c: (c == "Other", c))
        ]

    # Split into what's needed for the actual meals vs. what's only needed for sides/
    # extras (never both — an ingredient used by at least one main recipe is grouped
    # there even if a side also uses it, so nothing is double-counted or double-listed).
    # Purely presentational (Jemma: the merged list felt "daunting" to scan) — the
    # totals themselves are unchanged.
    main_items = [item for item in items if item["used_by_main"]]
    side_only_items = [item for item in items if not item["used_by_main"]]

    return {
        "items": items,
        "grouped": group_by_category(items),
        "grouped_main": group_by_category(main_items),
        "grouped_sides": group_by_category(side_only_items),
        "recipes_used": sorted(recipes_used, key=lambda r: r["name"]),
    }
