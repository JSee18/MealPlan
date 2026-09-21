# Meal Plan Generation — Nutritionist Rules (Draft v0.1)

This document captures the evidence-based logic the meal-plan algorithm should follow. It's the core differentiator vs. generic calorie-counting apps — treat it as living documentation and update as decisions firm up.

## 1. Energy & Macro Targets
- [ ] Calorie target derived from user inputs (age, gender, weight, height, activity level, goal) — professional selects the BMR equation via a dropdown per client rather than one fixed formula app-wide, since sport/performance goals often need a different equation than general population (e.g. Mifflin-St Jeor as the general-population default; Katch-McArdle or similar for athletic/high-activity clients where body composition is known)
- [ ] Macro splits vary by goal (e.g. sport/performance vs. weight loss vs. maintenance) — need target ranges defined per goal, not just one default split
- [ ] Protein: distribute across meals rather than front/back-loading (commonly cited guidance: ~20-40g per eating occasion, spread through the day) — confirm target per meal by bodyweight/goal
- [ ] Minimum calorie floors — meal plans should not generate implausibly low-calorie days regardless of stated goal (safety guardrail)

## 2. Micronutrient Coverage
- [ ] Reference standard priority: Irish guidelines first (Dept. of Health / FSAI RDAs), falling back to EU standards (EFSA Dietary Reference Values) where no Irish-specific figure exists
- [ ] Meal plan should be checked against RDAs/RNIs for key vitamins & minerals (not just calories/macros) — define which micronutrients to actively track (e.g. iron, calcium, vitamin D, B12, fibre, sodium as a ceiling not floor)
- [ ] Aim to meet all daily guideline nutrients, acknowledged as a genuinely hard constraint — treat as the target the algorithm optimises toward, with the professional-review step (see proposal doc) as the safety net for whatever it can't fully solve
- [ ] Nutrient-pairing rules to encode (e.g. iron + vitamin C for absorption; calcium timing vs. iron-rich meals)
- [ ] Fibre target per day, distributed reasonably across meals rather than dumped in one

## 2a. Warning Rules (flag, don't auto-block)
Rules that flag a plan for professional attention rather than silently generating or silently rejecting it — surfaced at the professional review step.
- [ ] Low protein relative to age-adjusted needs (e.g. older adults generally need higher protein per kg to offset age-related muscle loss — flag if a plan falls under that threshold)
- [ ] Saturated fat exceeding recommended ceiling (per Irish/EU guidance)
- [ ] Sodium exceeding recommended ceiling
- [ ] Any core micronutrient landing significantly under RDA despite optimisation (i.e. the algorithm couldn't fully solve for it given the client's preferences/exclusions)
- [ ] Calorie target itself outside a sensible safe range for the stated goal (safety guardrail, not just a data point)
- [ ] Additional warning rules to be added over time as edge cases come up in real use

## 3. Meal Structure & Distribution
- [ ] Number of meals/snacks is user-configurable, but each meal/snack should independently meet minimum "balance" criteria (protein + carb + fat + not-empty-calories), not just hit totals in aggregate
- [ ] Snacks should contribute meaningfully to daily micronutrient/fibre targets, not just be filler calories

## 4. Food Preference & Exclusion Handling
- [ ] Preferences (e.g. vegetarian, dislikes) act as hard filters before generation, not post-hoc substitution
- [ ] When a preference removes a major nutrient source (e.g. vegetarian removing a key iron/B12 source), the algorithm should compensate by prioritizing alternative sources — not just quietly under-deliver that nutrient

## 5. Guardrails / What the App Should NOT Do
- [ ] No generation of plans for disease-specific/clinical needs (diabetes, renal, etc.) — general public/goal-based only, with disclaimer to consult a professional for medical conditions
- [ ] No pathologising or restriction-glorifying language in generated plans/copy
- [ ] Avoid recommending anything a nutritionist wouldn't personally recommend a client (e.g. no fad elimination logic without cause)

## 6. Output Format ("Cookbook" Structure)
- [ ] Not a tracker — no calorie/macro numbers surfaced front-and-center to the client; numbers drive generation under the hood only
- [ ] Output structure per weekly plan:
  1. Contents/index (nav to each day/meal)
  2. Shopping list — ingredient quantities aggregated across the full week (not per-recipe, avoids duplicate buying)
  3. Daily meal plans — meals + snacks laid out per day
  4. Full recipe per meal/snack entry (ingredients + method, not just a name/macros — client should be able to cook directly from it)
- [ ] Read as a static weekly deliverable (like a PDF/printable book), not an interactive daily-use app

## 7. Batch Cooking Support
- [ ] Client-configurable option (e.g. "batch cook dinners," "batch cook X meals") — not forced by default, sits alongside a "fresh every day" mode
- [ ] Generation logic deliberately repeats a recipe across multiple days for flagged meal types, rather than optimizing for daily variety
- [ ] Batch-cook entries flagged clearly in the output (e.g. "cook Sunday, eat Tue/Thu/Sat") rather than listed as a fresh recipe under each day
- [ ] Nutritionist judgement call needed on which meal types batch well (stews, grain bowls, roasted veg, proteins) vs. which don't (salads, delicate fish, anything meant fresh) — encode as a tag/rule per recipe in the database
- [ ] Shopping list logic unaffected by batching (still aggregates total quantities), but fewer distinct recipes at larger quantities

## 8. Open Decisions
- Exact macro ranges per goal category
- Which micronutrients are "actively tracked" vs. background-only
- Whether sodium/saturated fat get treated as ceilings in the scoring logic
- Whether batch-cook eligibility is a fixed tag per recipe or something the algorithm can judge dynamically

---
*Update this doc as MSc coursework and reference materials firm up specific numbers/equations — treat it as the source of truth the algorithm is validated against.*
