# Nutrition Meal Plan Generator

A professional-facing application that generates a full week of meals and snacks for a client, tailored to their goals, and delivers it as a printable, cookbook-style weekly plan — not a food tracker.

## Why this exists

Most consumer nutrition apps (MyFitnessPal and similar) are built around logging what you already ate and reconciling it against a target. This app removes that entirely: the plan is prescribed upfront by a nutrition professional, and the client just cooks from it. No daily tracking, no macro-watching, no stress.

The core differentiator is that plans are generated from evidence-based nutritionist logic — calorie and macro targets derived per client, full micronutrient coverage against Irish/EU reference values, sensible meal structure, and nutrient-pairing rules — rather than a calorie calculator that just matches foods to a number.

## What this project demonstrates

**Software engineering** — a normalized schema built around real product requirements rather than a generic CRUD shape: an audit-trail pattern (`client_goal_history`) that keeps a full timeline of target revisions in sync with a live "current state" table via triggers, a persisted warning-flag system (`meal_plan_flags`) that keeps automated rule-checking accountable to human review rather than silently auto-correcting or auto-rejecting, and a reference-data table (`nutrient_targets`) that separates "what the rules are" from "what the code does," so nutrition guidance can be updated without a code change.

**Applied nutrition science** — calorie and macro targets derived per client goal (BMR equation selectable per client, since sport/performance clients often need a different equation than general population), full micronutrient optimisation against Irish/EU reference standards (Dept. of Health / FSAI first, EFSA fallback) rather than calories and macros alone, nutrient-pairing logic (e.g. iron + vitamin C for absorption), and explicit safety guardrails that keep the tool scoped to general-population goal-based plans rather than clinical nutrition.

## Who it's for

- **Primary (build first):** nutrition professionals and coaches managing plans for multiple clients.
- **Secondary (later):** individual consumers generating their own single-profile plan, once the professional-facing side is validated.

## How it works

1. **Client profile** — age, gender, weight, height, activity level, goal, food preferences/exclusions, meal/snack structure, batch-cooking preference. Preferences act as hard filters applied *before* generation, not substituted after the fact.
2. **Rules engine** — derives a calorie target (professional selects the BMR equation per client — Mifflin-St Jeor as the general-population default, Katch-McArdle for athletic/high-activity clients), macro split by goal, and checks every generated plan against per-nutrient RDA/ceiling targets (Irish Dept. of Health / FSAI first, EFSA as fallback).
3. **Generation** — hand-curated recipes and ingredients (linked to USDA FoodData Central where possible) are assembled into a full week that meets calorie, macro, and micronutrient targets simultaneously, respecting batch-cooking preferences where enabled.
4. **Weekly aggregation** — ingredient quantities are summed across the whole week (not per-recipe) into a single shopping list, and batch-cooked meals are flagged with a cook day and eat days.
5. **Professional review** — every generated plan is a draft until the professional approves it, edits specific meals, or triggers a regeneration. Any warning flags raised by the rules engine (low protein for the client's age band, saturated fat or sodium over ceiling, a micronutrient landing short of RDA despite optimisation, calorie target outside a sensible range) surface here rather than being silently auto-corrected or silently ignored.
6. **Cookbook output** — the final deliverable is a static weekly document: contents/index, shopping list, daily meal plans, and a full recipe (ingredients + method) per meal. No calorie or macro numbers are shown to the client — those exist only to drive generation.

## Guardrails

- No plans for disease-specific or clinical needs (diabetes, renal, etc.) — general public, goal-based only (sport/performance, weight loss, maintenance), with a standard disclaimer to consult a professional for medical conditions.
- No pathologising or restriction-glorifying language in generated copy.
- Minimum calorie floors and a sensible safe range per goal, enforced as hard guardrails rather than just data points.

## Database

SQLite to start (file-based, no server), with an upgrade path to PostgreSQL if/when multi-user hosting is needed. Full schema: [`schema.sql`](./schema.sql).

| Table | Purpose |
|---|---|
| `clients` | Professional's client profiles — stats, activity level, goal, current calorie/macro targets |
| `client_goal_history` | Full audit trail of target revisions over time (what changed, when, why) — `clients` always holds the current values, synced automatically via triggers whenever a new revision is logged |
| `nutrient_targets` | RDA/RNI and ceiling reference values per nutrient, age band, and gender (Irish FSAI first, EFSA fallback) — what the generation engine and warning rules check against |
| `ingredients` | Hand-curated ingredient data, linked to USDA FoodData Central where possible — full macro and micronutrient profile per 100g (31 tracked nutrients: macros, vitamins A/D/E/K/C/B-complex/folate, and key minerals) |
| `recipes` | Hand-curated recipes with full method, tagged for batch-cook suitability |
| `recipe_ingredients` | Join table linking recipes to ingredients with quantity, plus a human-readable display quantity/unit for the printed cookbook |
| `meal_plans` | A generated weekly plan for a client, with draft/reviewed/sent status |
| `meal_plan_entries` | Individual day/meal-slot entries within a plan, including batch-cook flags |
| `meal_plan_flags` | Warning flags raised by the rules engine on a given plan, persisted for the professional review step to see, resolve, and annotate |

To set up a local database:

```bash
sqlite3 mealplan.db < schema.sql
```

## Data & tooling approach

- **Recipes and ingredients** are hand-curated, not sourced generically — this is where the nutritionist point of view actually lives. Entry happens in Excel first (easy to review/edit), then imports into the database via script.
- **USDA FoodData Central** is used as a fill-in/lookup layer for nutrient values, not as the primary content source.

## Regulatory scope

Scoped to general-public, goal-based plans (sport, weight loss, maintenance) — not disease-specific or clinical nutrition, which keeps this in nutritionist (not dietitian/medical) territory. Standard disclaimer applies: not medical advice, consult a professional for medical conditions.

## Status

Early development. The database schema and the evidence-based rules the generation engine will follow are defined; the generation engine, review workflow, and cookbook output itself are in progress.

## Roadmap

1. Build the professional-side MVP: client profile management, generation engine, cookbook output.
2. Test with real clients, gather feedback on recipe quality, plan accuracy, and batch-cooking usefulness.
3. Refine the nutritionist rules and generation logic based on real feedback.
4. Evaluate a consumer-facing version once the professional side is validated.

## License

All rights reserved. This code is shared publicly for portfolio and evaluation purposes (e.g. review by potential employers or collaborators) — see [`LICENSE`](./LICENSE). No permission is granted to copy, modify, or reuse it.
