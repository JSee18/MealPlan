import json
import sqlite3
from pathlib import Path

import streamlit as st

from calculations import (
    ACTIVITY_DESCRIPTIONS,
    ACTIVITY_MULTIPLIERS,
    calculate_bmr,
    calculate_calorie_target,
    calculate_macros,
)

DB_PATH = Path(__file__).parent.parent / "database" / "mealplan.db"

st.set_page_config(page_title="Add Client", page_icon="📋")
st.title("📋 Add Client")


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_dietary_vocabulary(conn):
    """Pull the exact allergen / suitable-for vocabulary already in use by
    recipes, so the client form's options always match what's filterable.
    """
    allergens, suitable_for = set(), set()
    for (tags_json,) in conn.execute("SELECT dietary_tags FROM recipes"):
        tags = json.loads(tags_json)
        allergens.update(tags["allergy_info"]["contains"])
        allergens.update(tags["allergy_info"]["may_contain"])
        suitable_for.update(tags["suitable_for"])
    return sorted(allergens), sorted(suitable_for)


conn = get_connection()
allergen_options, suitable_for_options = get_dietary_vocabulary(conn)
ingredient_options = [row[0] for row in conn.execute("SELECT DISTINCT name FROM ingredients ORDER BY name")]

st.subheader("Goal")
# Kept outside the form (plain widgets rerun immediately; form widgets only rerun on
# submit) so the deficit field can actually appear/disappear as the goal changes.
goal = st.selectbox("Goal", ["weight_loss", "maintenance", "muscle_gain", "sport_performance"])
deficit_kcal = 0
if goal == "weight_loss":
    deficit_kcal = st.number_input(
        "Calorie deficit (kcal/day, subtracted from maintenance calories)",
        min_value=0, max_value=1500, value=500, step=50,
    )

with st.form("add_client_form"):
    st.subheader("Client details")
    name = st.text_input("Client name")
    col1, col2, col3 = st.columns(3)
    age = col1.number_input("Age", min_value=18, max_value=100, value=30)
    gender = col2.selectbox("Gender", ["female", "male"])
    weight_kg = col3.number_input("Weight (kg)", min_value=30.0, max_value=250.0, value=70.0, step=0.5)
    height_cm = st.number_input("Height (cm)", min_value=120.0, max_value=220.0, value=165.0, step=0.5)

    st.subheader("Energy calculation")
    col4, col5 = st.columns(2)
    bmr_equation = col4.selectbox(
        "BMR equation", ["mifflin_st_jeor", "katch_mcardle"],
        format_func=lambda x: "Mifflin-St Jeor" if x == "mifflin_st_jeor" else "Katch-McArdle",
    )
    activity_level = col5.selectbox(
        "Activity level", list(ACTIVITY_MULTIPLIERS.keys()),
        format_func=lambda x: f"{x.replace('_', ' ').title()} ({ACTIVITY_DESCRIPTIONS[x]})", index=2,
    )
    body_fat_percentage = st.number_input(
        "Body fat % (only needed for Katch-McArdle)", min_value=0.0, max_value=70.0, value=0.0, step=0.5
    )

    st.subheader("Macros")
    protein_target_g_per_kg = st.number_input(
        "Protein target (g/kg bodyweight)", min_value=0.5, max_value=3.0, value=1.6, step=0.1
    )
    col6, col7 = st.columns(2)
    fat_percentage_min = col6.number_input("Fat % — min", min_value=10.0, max_value=50.0, value=20.0, step=1.0)
    fat_percentage_max = col7.number_input("Fat % — max", min_value=10.0, max_value=50.0, value=35.0, step=1.0)

    st.subheader("Preferences & structure")
    suitable_for = st.multiselect("Diet style (client must eat only recipes suitable for these)", suitable_for_options)
    exclusions = st.multiselect("Allergies / exclusions (excludes recipes that contain OR may contain these)", allergen_options)
    disliked_ingredients = st.multiselect(
        "Disliked ingredients (excludes any recipe using these — a preference, not an allergy)",
        ingredient_options,
    )
    col8, col9 = st.columns(2)
    meals_per_day = col8.number_input("Meals per day", min_value=1, max_value=6, value=3)
    snacks_per_day = col9.number_input("Snacks per day", min_value=0, max_value=6, value=2)
    batch_cooking_enabled = st.checkbox("Batch cooking enabled")
    has_blender = st.checkbox("Has a blender", value=True, help="Unchecking excludes recipes that need a blender/food processor (e.g. smoothies, blended soups).")

    submitted = st.form_submit_button("Calculate & save client")

if submitted:
    if not name:
        st.error("Client name is required.")
    else:
        bmr = calculate_bmr(
            bmr_equation, weight_kg, height_cm, age, gender,
            body_fat_percentage=body_fat_percentage if bmr_equation == "katch_mcardle" else None,
        )
        maintenance_calories = calculate_calorie_target(bmr, activity_level)
        calorie_target = maintenance_calories - deficit_kcal if goal == "weight_loss" else maintenance_calories
        macros = calculate_macros(
            calorie_target, weight_kg, protein_target_g_per_kg, fat_percentage_min, fat_percentage_max
        )

        preferences = {
            "suitable_for": suitable_for,
            "exclusions": exclusions,
            "disliked_ingredients": disliked_ingredients,
        }

        conn.execute(
            """
            INSERT INTO clients (
                name, age, gender, weight_kg, height_cm, activity_level, body_fat_percentage,
                goal, bmr_equation, calorie_target, protein_target_g_per_kg,
                fat_percentage_min, fat_percentage_max, macro_targets, preferences,
                meals_per_day, snacks_per_day, batch_cooking_enabled, has_blender
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, age, gender, weight_kg, height_cm, activity_level,
                body_fat_percentage if bmr_equation == "katch_mcardle" else None,
                goal, bmr_equation, round(calorie_target), protein_target_g_per_kg,
                fat_percentage_min, fat_percentage_max, json.dumps(macros), json.dumps(preferences),
                meals_per_day, snacks_per_day, batch_cooking_enabled, has_blender,
            ),
        )
        conn.commit()

        st.success(f"Saved {name} to the database.")
        st.subheader("Calculated targets")
        if goal == "weight_loss":
            st.caption(f"Maintenance calories: {maintenance_calories:.0f} kcal − {deficit_kcal:.0f} kcal deficit")
            if calorie_target < bmr:
                st.warning(
                    f"This calorie target ({calorie_target:.0f} kcal) is below {name}'s BMR "
                    f"({bmr:.0f} kcal) — that's a fairly aggressive deficit, worth double-checking."
                )
        cols = st.columns(4)
        cols[0].metric("Calorie target", f"{calorie_target:.0f} kcal")
        cols[1].metric("Protein", f"{macros['protein_g']:.0f} g")
        cols[2].metric("Fat", f"{macros['fat_g']:.0f} g")
        cols[3].metric("Carbs", f"{macros['carbs_g']:.0f} g")
        st.caption(f"Fat % used: {macros['fat_percentage_used']:.1f}% (midpoint of {fat_percentage_min:.0f}-{fat_percentage_max:.0f}%)")

conn.close()
