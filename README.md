# Nutrition Meal Plan Generator

A professional-facing application that generates a full week of meals and snacks for a client, tailored to their calorie and macro targets, and delivers it as a printable, cookbook-style PDF with a shopping list — not a food tracker.

## Why this exists

Most consumer nutrition apps (MyFitnessPal and similar) are built around logging what you already ate and reconciling it against a target. This app removes that entirely: the plan is prescribed upfront by a nutrition professional, and the client just cooks from it. No daily tracking, no macro-watching, no stress.

The core differentiator is that plans are generated from evidence-based nutritionist logic — calorie and macro targets derived per client, sensible meal structure, and per-meal balancing — rather than a calorie calculator that just matches foods to a number.

## What this project demonstrates

**Software engineering** — a normalized SQLite schema built around real product requirements rather than a generic CRUD shape, a combinatorial meal-selection engine with a documented scoring model, a multi-page Streamlit interface, and a reportlab-generated PDF export. Reference data (`nutrient_targets`) is kept separate from code, so nutrition guidance can be updated without a code change. Several design decisions came from generating real plans, inspecting the output, and fixing what looked wrong (see [Design decisions](#design-decisions)).

**Applied nutrition science** — calorie and macro targets derived per client goal, with the BMR equation selectable per client (Mifflin-St Jeor as the general-population default, Katch-McArdle for athletic clients where body fat is known), an activity multiplier, a configurable deficit for weight loss, and a protein-per-kg / fat-percentage-range macro split. Ingredient data is sourced from the UK McCance & Widdowson tables (CoFID) and, wherever available, real product labels — not generic estimates.

## Who it's for

- **Primary (built first):** nutrition professionals and coaches managing plans for multiple clients.
- **Secondary (later):** individual consumers generating their own single-profile plan, once the professional-facing side is validated.

## Features

- **Client profiles** — age, gender, weight, height, activity level (with plain-language training-frequency descriptions), goal, protein target, fat-percentage range, calorie deficit for weight-loss goals, dietary suitability tags, allergen exclusions, disliked ingredients, and whether the client owns a blender.
- **Direct target editing** — override calorie and macro targets, or update weight, without recalculating from scratch.
- **7-day plan generation** — breakfast, lunch, dinner and snacks for each day, scored against the client's calorie, protein, carb, fat and fibre targets.
- **Sides system** — small add-ons (vegetables, fruit, protein, bread toppings, a glass of milk) chosen automatically to close the remaining calorie/macro gap on each meal, built from real product labels.
- **Recipe variety control** — each meal type draws from a small rotating set of recipes across the week, which keeps plans predictable to cook and the shopping list short.
- **Shopping list** — aggregated across the whole week, converted to natural units (3 eggs rather than 150g), deduplicated to one product per family (one Babybel type, one milk), and split into "For Your Meals" and "Sides & Extras".
- **Clickable recipes** — full ingredients and method in a popup from anywhere a recipe is listed.
- **PDF export** — shopping list first, then each day's meal summary and full recipes, with a configurable breakfast/lunch/dinner/snack order and sides visually distinguished from main meals.

## How it works

1. **Client profile** — inputs above. Preferences act as hard filters applied *before* generation, not substituted after the fact.
2. **Targets** — BMR from the chosen equation, multiplied by the activity level for TDEE, adjusted by any deficit; protein from g/kg, fat from the midpoint of the chosen percentage range, carbohydrate as the remainder.
3. **Generation** — for each day the engine searches combinations of eligible recipes for the best fit to the day's targets, scoring each meal against its own fair share of the day so one oversized meal can't hide behind a small one. Sides are then optimised against the chosen meals.
4. **Weekly aggregation** — recipe quantities are summed across the week into one shopping list; batch-cooked recipes are bought for the number of times they're cooked, not eaten.
5. **Output** — an on-screen plan with per-day totals against target, and a printable PDF.

## Design decisions

- **Brute-force search, on purpose.** Meal selection uses `itertools` over the eligible recipe pool rather than a solver. At this pool size it is fast, easy to reason about, and easy to explain to a non-technical user; the module docstring documents the trade-off.
- **Two-stage side selection.** Sides are optimised *after* the meals are chosen (additive), rather than jointly (multiplicative), which avoids a combinatorial explosion as the side pool grows.
- **Per-slot scoring.** Early versions scored only the day total, which allowed a 600 kcal breakfast next to a 250 kcal lunch. Scoring each meal against its share of the day fixed that.
- **Asymmetric fibre penalty.** Fibre is a floor, not a ceiling: free up to target, penalised above it, after unconstrained generation produced ~50 g/day.
- **Targeted, not blanket, restrictions.** A blanket "cap every side category" rule was tried and reverted after it measurably worsened calorie fit, because a category with many near-identical entries (bread toppings) crowded out the vegetable sides doing the real gap-closing. The current approach deduplicates only specific known product families.
- **Soft preferences over hard bans.** Ingredient preferences (for example favouring whole eggs over egg whites) add a scoring penalty rather than excluding recipes, so a preference can never leave a slot unfillable.

## Data

SQLite (file-based, no server), with an upgrade path to PostgreSQL if multi-user hosting is ever needed. The database is included in the repository. Full schema: [`schema.sql`](./schema.sql).

| Table | Purpose |
|---|---|
| `clients` | Client profiles — stats, activity level, goal, targets, preferences |
| `nutrient_targets` | EFSA reference values (RDA/AI and ceilings) per nutrient, age band and gender |
| `ingredients` | Hand-curated ingredient data per 100g: macros, fibre, saturated fat, sodium and the main vitamins and minerals, plus shopping-list metadata (category, natural unit size) |
| `recipes` | Recipes with method, servings, dietary tags, batch-cook suitability, blender requirement, and (for sides) which meal types they pair with |
| `recipe_ingredients` | Links recipes to ingredients with an exact gram quantity plus a human-readable display quantity for the printed cookbook |
| `meal_plans`, `meal_plan_entries`, `meal_plan_flags` | Schema for persisting generated plans and rule-check warnings for professional review (not yet used by the app) |

The database currently holds 148 ingredients and 66 recipes (29 main-meal and snack recipes plus 37 side add-ons).

**Data approach.** Recipes and ingredients are hand-curated, not sourced generically — this is where the nutritionist point of view lives. Generic ingredients use CoFID values; branded products use the values printed on the real label, cross-checked against the ingredient list. Vitamin and mineral coverage across ingredients is partial (roughly 40–65%), and monounsaturated/polyunsaturated fat is not yet tracked, so micronutrient totals should be read as floors rather than exact figures.

## Running it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The pages are in the sidebar: add a client, edit their targets, and generate a daily or weekly plan.

## Scope and guardrails

- Scoped to general-population, goal-based plans (sport, weight loss, maintenance) — not disease-specific or clinical nutrition, which keeps this in nutritionist rather than dietitian or medical territory. Standard disclaimer applies: not medical advice; consult a professional for medical conditions.
- No pathologising or restriction-glorifying language in generated copy.

## Status

Working end to end for the professional workflow: client setup, 7-day generation with sides, shopping list, and PDF export. The recipe library is still growing.

## Roadmap

1. **Micronutrient checking** — run each generated day against the `nutrient_targets` reference values and surface any shortfalls, with suggestions. The reference data and ingredient coverage are in place; this has so far been done as a one-off analysis rather than a built feature.
2. **Professional review workflow** — save plans as drafts, raise warning flags (calorie outside a safe range, saturated fat or sodium over ceiling, low protein), and require approval before a plan is sent, using the existing plan and flag tables.
3. **Guardrails** — enforce minimum calorie floors and safe ranges per goal in the generator.
4. **Nutrient-pairing rules** — for example iron alongside vitamin C for absorption.
5. **Wider recipe library**, then test with real clients and refine the rules from their feedback.
6. Evaluate a consumer-facing version once the professional side is validated.

## License

All rights reserved. This code is shared publicly for portfolio and evaluation purposes (e.g. review by potential employers or collaborators) — see [`LICENSE`](./LICENSE). No permission is granted to copy, modify, or reuse it.
