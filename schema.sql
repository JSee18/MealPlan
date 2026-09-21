-- Nutrition meal plan app — database schema (SQLite)
-- Companion to: nutrition-meal-plan-app-proposal.md, meal-plan-nutritionist-rules.md
-- Revision v0.2 — addresses gaps found reviewing v0.1 against the rules doc (see inline notes)

PRAGMA foreign_keys = ON;

-- Professional's client profiles
CREATE TABLE clients (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    age                     INTEGER,
    gender                  TEXT,
    weight_kg               REAL,                        -- required input for Mifflin-St Jeor / Katch-McArdle
    height_cm                REAL,                        -- required input for Mifflin-St Jeor
    activity_level           TEXT,                        -- e.g. 'sedentary','light','moderate','active','very_active' — converts BMR to TDEE
    body_fat_percentage      REAL,                        -- required input for Katch-McArdle (lean body mass); NULL if using Mifflin-St Jeor
    goal                    TEXT,                        -- e.g. 'sport', 'weight_loss', 'maintenance'
    bmr_equation            TEXT,                        -- e.g. 'mifflin_st_jeor', 'katch_mcardle'
    calorie_target          INTEGER,                     -- computed: BMR x activity multiplier (TDEE)
    protein_target_g_per_kg REAL,                        -- professional's input, e.g. 1.6 — drives protein_g in macro_targets
    fat_percentage_min      REAL,                        -- professional's input range, e.g. 25
    fat_percentage_max      REAL,                        -- e.g. 30 — midpoint used for the fat_g calculation
    macro_targets           TEXT,                        -- computed JSON: {"protein_g":88,"fat_g":59,"carbs_g":264,"fat_percentage_used":27.5}
    preferences             TEXT,                        -- JSON: {"suitable_for":["vegetarians"],"exclusions":["Milk","Nuts"]}
                                                           -- suitable_for / exclusions vocabulary matches recipes.dietary_tags exactly
                                                           -- (suitable_for, allergy_info.contains/may_contain) so filtering is a direct match
    meals_per_day           INTEGER,
    snacks_per_day          INTEGER,
    batch_cooking_enabled   BOOLEAN DEFAULT 0,
    has_blender             BOOLEAN DEFAULT 1,             -- if false, recipes.requires_blender=1 recipes are excluded entirely
    created_at              TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Reference nutrient targets (RDAs/RNIs and ceilings), keyed by nutrient + age band + gender.
-- Populate Irish guidance (Dept. of Health / FSAI) first, EFSA DRVs as fallback where no
-- Irish-specific figure exists — `source` records which was used per row.
-- This is what the generation engine optimises against and what the warning rules (rules doc §2a)
-- check plans against — without it there's nowhere for those RDA figures to actually live.
CREATE TABLE nutrient_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nutrient        TEXT NOT NULL,                       -- 'protein','iron','calcium','vitamin_d','vitamin_b12','fibre','sodium','saturated_fat', etc.
    age_min         INTEGER NOT NULL,
    age_max         INTEGER NOT NULL,
    gender          TEXT NOT NULL DEFAULT 'any',          -- 'male' | 'female' | 'any'
    target_type     TEXT NOT NULL,                        -- 'rda' (floor to meet) | 'ceiling' (not to exceed) | 'ai' (adequate intake)
    value           REAL NOT NULL,
    unit            TEXT NOT NULL,                        -- 'g','mg','mcg', etc.
    per             TEXT NOT NULL DEFAULT 'day',           -- 'day' | 'kg_bodyweight' (e.g. protein g/kg for older adults)
    source          TEXT NOT NULL,                        -- 'irish_fsai' | 'efsa'
    notes           TEXT
);

-- Ingredients (linked to USDA FoodData Central where possible).
-- Nutrient set below matches Jemma's "Nutrient Quick Reference Guide" (Nutrient_Requirements.docx) —
-- units follow that doc's Rec. Intake units so ingredient values line up with nutrient_targets rows.
CREATE TABLE ingredients (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    fdc_id                  TEXT,                        -- nullable; USDA FoodData Central ID
    category                TEXT,                        -- shopping-list grouping, e.g. 'Vegetables', 'Meat & Poultry' —
                                                           -- see generator.py generate_shopping_list() for how it's used
    shopping_unit_size_g    REAL,                        -- weight/volume of ONE natural shopping unit, e.g. 50 for an egg,
                                                           -- 118 for a banana — lets the shopping list show "3 eggs" instead
                                                           -- of "150g"; NULL means display in g/kg as normal
    shopping_unit_name      TEXT,                        -- singular unit label to pair with shopping_unit_size_g, e.g. 'egg',
                                                           -- 'banana', 'clove of garlic', 'stock cube'
    exclude_from_shopping_list BOOLEAN DEFAULT 0,         -- e.g. Water — used in recipes but never actually bought

    -- Macronutrients (per 100g)
    calories_per_100g       REAL,                        -- kcal
    protein_per_100g        REAL,                        -- g
    carbs_per_100g          REAL,                        -- g
    fat_per_100g            REAL,                        -- g
    saturated_fat_per_100g  REAL,                        -- g; needed for warning rule 2a (saturated fat ceiling)
    fibre_per_100g          REAL,                        -- g
    alcohol_per_100g        REAL,                        -- g; only relevant to a handful of recipes/ingredients

    -- Vitamins (per 100g)
    vitamin_a_per_100g      REAL,                        -- µg (retinol)
    vitamin_d_per_100g      REAL,                        -- µg
    vitamin_e_per_100g      REAL,                        -- mg
    vitamin_k_per_100g      REAL,                        -- µg
    vitamin_c_per_100g      REAL,                        -- mg; needed to encode the iron + vitamin C pairing rule (rules doc §2)
    vitamin_b1_per_100g     REAL,                        -- mg (thiamine)
    vitamin_b2_per_100g     REAL,                        -- mg (riboflavin)
    vitamin_b3_per_100g     REAL,                        -- mg (niacin)
    vitamin_b6_per_100g     REAL,                        -- mg (pyridoxine)
    vitamin_b7_per_100g     REAL,                        -- µg (biotin)
    vitamin_b12_per_100g    REAL,                        -- µg (cobalamin)
    folate_per_100g         REAL,                        -- µg (vitamin B9 / folic acid)

    -- Minerals (per 100g)
    calcium_per_100g        REAL,                        -- mg
    iron_per_100g           REAL,                        -- mg
    zinc_per_100g           REAL,                        -- mg
    iodine_per_100g         REAL,                        -- µg
    sodium_per_100g         REAL,                        -- mg
    potassium_per_100g      REAL,                        -- mg
    magnesium_per_100g      REAL,                        -- mg
    phosphorus_per_100g     REAL,                        -- mg
    selenium_per_100g       REAL                         -- µg
    -- add further micronutrient columns as the rules doc's tracked-nutrient list is finalised
);

-- Recipes (hand-curated, method included so the output can be cooked from directly)
CREATE TABLE recipes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    meal_type               TEXT,                        -- 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'side'
    method                  TEXT,                        -- full cooking instructions
    base_servings           INTEGER NOT NULL DEFAULT 1,   -- how many servings the ingredient list below yields, at quantity_g x1
    batch_cook_suitable     BOOLEAN DEFAULT 0,
    requires_blender        BOOLEAN DEFAULT 0,            -- method genuinely needs a blender/food processor/stick blender
                                                           -- (not just "can optionally blend") — excluded entirely for clients
                                                           -- with clients.has_blender=0
    side_pairs_with         TEXT,                        -- JSON array, only set when meal_type='side', e.g. ["breakfast","snack"] —
                                                           -- which meal slots this side realistically accompanies (fruit with
                                                           -- breakfast, veg with lunch/dinner, etc.) so the generator can pair
                                                           -- a chosen side with a sensible meal for display rather than showing
                                                           -- it as an unattached extra — see generator.py generate_weekly_plan()
    is_protein_topper       BOOLEAN DEFAULT 0,             -- only set when meal_type='side', e.g. Grilled Chicken Breast —
                                                           -- a side whose whole point is adding a meat/fish protein source,
                                                           -- so it shouldn't be offered to a main that already has one
    no_added_protein_needed BOOLEAN DEFAULT 0,             -- a breakfast/lunch/dinner/snack recipe that already contains its
                                                           -- own meat/fish protein (chicken, turkey, beef, salmon, mackerel,
                                                           -- etc.) — is_protein_topper sides are skipped for these, so e.g.
                                                           -- Grilled Chicken Breast never gets added on top of a dish that's
                                                           -- already chicken- or fish-based
    dietary_tags            TEXT                         -- JSON object, set at curation time against the recipe's actual ingredients.
                                                           -- Mirrors the structure of a real UK/Irish food label so it stays directly
                                                           -- checkable against ingredient labels, and so the generator can filter by it:
                                                           --   allergy_info.contains     — the 14 EU allergens actually present
                                                           --   allergy_info.may_contain  — cross-contamination warnings
                                                           --   suitable_for              — diet-style claims, e.g. "vegetarians","vegans"
                                                           --   free_from                 — explicit "free from" claims, e.g. "gluten","dairy"
                                                           -- e.g. {"allergy_info":{"contains":["Milk"],"may_contain":["Nuts"]},
                                                           --       "suitable_for":["vegetarians"],"free_from":["gluten"]}
);

-- Join table: which ingredients (and how much) go into each recipe.
-- quantity_g is always grams (or ml for liquids) and drives all nutrient math; display_quantity/
-- display_unit is what actually gets printed in the cookbook (e.g. "1", "cup"). Both are set at
-- curation time — avoids needing a separate unit-conversion table since entry is hand-curated anyway.
CREATE TABLE recipe_ingredients (
    recipe_id           INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id        INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE RESTRICT,
    quantity_g            REAL NOT NULL,                 -- grams/ml — used for all nutrient calculations
    display_quantity      TEXT,                          -- human-readable amount, e.g. '1', '1/2'
    display_unit           TEXT,                         -- human-readable unit, e.g. 'cup', 'tbsp', 'g'
    PRIMARY KEY (recipe_id, ingredient_id)
);

-- A generated weekly plan for a client
CREATE TABLE meal_plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    week_start      TEXT,                                -- date, ISO format
    status          TEXT DEFAULT 'draft',                -- 'draft' | 'reviewed' | 'sent'
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Individual day/meal-slot entries within a meal plan
CREATE TABLE meal_plan_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_plan_id        INTEGER NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
    recipe_id           INTEGER NOT NULL REFERENCES recipes(id) ON DELETE RESTRICT,
    day                 TEXT,                            -- 'Mon','Tue', etc.
    meal_slot           TEXT,                            -- 'breakfast','lunch','dinner','snack_1', etc.
    portion_multiplier  REAL NOT NULL DEFAULT 1.0,        -- scales recipe's base_servings quantities to fit this client's target for the slot
    is_batch_cook        BOOLEAN DEFAULT 0,
    cook_day              TEXT                            -- day this entry is actually cooked, if batch-cooked
);

-- Warning flags raised by the rules engine on a given plan (rules doc §2a) — persisted so the
-- professional review step (proposal §4.6) has something concrete to see, resolve, and record a
-- decision against, rather than flags existing only transiently at generation time.
CREATE TABLE meal_plan_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_plan_id    INTEGER NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
    flag_type       TEXT NOT NULL,                       -- 'low_protein','high_saturated_fat','high_sodium','micronutrient_shortfall','calorie_out_of_range', etc.
    nutrient        TEXT,                                -- nullable; nutrient this flag concerns, if applicable
    detail          TEXT,                                -- e.g. 'Iron at 62% of RDA despite optimisation'
    status          TEXT NOT NULL DEFAULT 'open',         -- 'open' | 'resolved' | 'acknowledged'
    resolution_note TEXT,                                -- professional's note on how it was handled
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TEXT
);

-- Helpful indexes
CREATE INDEX idx_meal_plans_client ON meal_plans(client_id);
CREATE INDEX idx_entries_meal_plan ON meal_plan_entries(meal_plan_id);
CREATE INDEX idx_entries_recipe ON meal_plan_entries(recipe_id);
CREATE INDEX idx_recipe_ingredients_recipe ON recipe_ingredients(recipe_id);
CREATE INDEX idx_recipe_ingredients_ingredient ON recipe_ingredients(ingredient_id);
CREATE INDEX idx_nutrient_targets_lookup ON nutrient_targets(nutrient, gender, age_min, age_max);
CREATE INDEX idx_flags_meal_plan ON meal_plan_flags(meal_plan_id);
