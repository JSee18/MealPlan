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
    activity_level          TEXT,                        -- 'sedentary' | 'lightly_active' | 'moderately_active' | 'very_active' | 'extra_active'
    goal                    TEXT,                        -- e.g. 'sport', 'weight_loss', 'maintenance'
    bmr_equation            TEXT,                        -- e.g. 'mifflin_st_jeor', 'katch_mcardle'
    calorie_target          INTEGER,
    macro_targets           TEXT,                        -- e.g. JSON: {"protein_g":150,"carbs_g":200,"fat_g":70}
    preferences             TEXT,                        -- e.g. JSON: {"exclusions":["dairy"],"style":"vegetarian"}
    meals_per_day           INTEGER,
    snacks_per_day          INTEGER,
    batch_cooking_enabled   BOOLEAN DEFAULT 0,
    created_at              TEXT DEFAULT CURRENT_TIMESTAMP
);

-- History of goal/target revisions for a client. Targets get revised over time in real coaching
-- practice — activity level corrected, calorie target adjusted after reviewing actual progress,
-- protein re-based to a fixed gram figure rather than a percentage, etc. — and `clients` only ever
-- holds the current values. This preserves what was set, when it took effect, and why, rather than
-- each edit silently overwriting the previous state with no trace.
CREATE TABLE client_goal_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    effective_date  TEXT NOT NULL,                       -- date this revision took effect, ISO format
    goal            TEXT,                                -- e.g. 'sport', 'weight_loss', 'maintenance'
    activity_level  TEXT,                                -- same values as clients.activity_level
    bmr_equation    TEXT,
    calorie_target  INTEGER,
    macro_targets   TEXT,                                -- JSON, same shape as clients.macro_targets
    reason          TEXT,                                -- professional's note on why this changed
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
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
    meal_type               TEXT,                        -- 'breakfast' | 'lunch' | 'dinner' | 'snack'
    method                  TEXT,                        -- full cooking instructions
    base_servings           INTEGER NOT NULL DEFAULT 1,   -- how many servings the ingredient list below yields, at quantity_g x1
    batch_cook_suitable     BOOLEAN DEFAULT 0
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
CREATE INDEX idx_goal_history_client ON client_goal_history(client_id, effective_date);

-- Triggers: keep `clients` holding the current/live targets while client_goal_history keeps the
-- full timeline. Day-to-day reads (meal plan generation, dashboards) can query `clients` directly
-- without joining to history; the audit trail lives alongside it rather than replacing it.
-- NOTE: trg_sync_client_goal assumes history rows are inserted in chronological order (i.e. the
-- most recently inserted row is always the most current). If you ever need to backfill an
-- out-of-order historical entry, insert it directly and re-run an UPDATE on `clients` afterwards
-- rather than relying on this trigger to get the "current" values right.

-- Every new client automatically gets an initial history entry, so the audit trail starts at
-- creation rather than only from the first later edit.
CREATE TRIGGER trg_seed_client_goal_history
AFTER INSERT ON clients
BEGIN
    INSERT INTO client_goal_history (client_id, effective_date, goal, activity_level, bmr_equation, calorie_target, macro_targets, reason)
    VALUES (NEW.id, NEW.created_at, NEW.goal, NEW.activity_level, NEW.bmr_equation, NEW.calorie_target, NEW.macro_targets, 'Initial targets set at client creation');
END;

-- Whenever a new revision is logged, sync it back onto `clients` as the current values.
CREATE TRIGGER trg_sync_client_goal
AFTER INSERT ON client_goal_history
BEGIN
    UPDATE clients
    SET goal           = NEW.goal,
        activity_level = NEW.activity_level,
        bmr_equation   = NEW.bmr_equation,
        calorie_target = NEW.calorie_target,
        macro_targets  = NEW.macro_targets
    WHERE id = NEW.client_id;
END;
