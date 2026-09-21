import sqlite3
from pathlib import Path

import streamlit as st

from ui_helpers import ingredient_line

DB_PATH = Path(__file__).parent / "database" / "mealplan.db"

st.set_page_config(page_title="Meal Plan Generator", page_icon="🥗")


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_recipes(conn):
    return conn.execute("SELECT id, name, meal_type, base_servings FROM recipes ORDER BY name").fetchall()


def get_recipe_nutrition(conn, recipe_id, servings):
    row = conn.execute(
        """
        SELECT
            SUM(i.calories_per_100g * ri.quantity_g / 100.0),
            SUM(i.protein_per_100g * ri.quantity_g / 100.0),
            SUM(i.carbs_per_100g * ri.quantity_g / 100.0),
            SUM(i.fat_per_100g * ri.quantity_g / 100.0),
            SUM(i.fibre_per_100g * ri.quantity_g / 100.0)
        FROM recipe_ingredients ri
        JOIN ingredients i ON i.id = ri.ingredient_id
        WHERE ri.recipe_id = ?
        """,
        (recipe_id,),
    ).fetchone()
    kcal, protein, carbs, fat, fibre = row
    return {
        "kcal": kcal / servings,
        "protein": protein / servings,
        "carbs": carbs / servings,
        "fat": fat / servings,
        "fibre": fibre / servings,
    }


st.title("🥗 Meal Plan Generator")
st.caption("Shell v0 — confirms the database connection works. The real plan generator comes next.")

conn = get_connection()
recipes = get_recipes(conn)

st.metric("Recipes in database", len(recipes))

recipe_names = [r[1] for r in recipes]
selected_name = st.selectbox("Browse a recipe", recipe_names)
selected = next(r for r in recipes if r[1] == selected_name)
recipe_id, name, meal_type, base_servings = selected

nutrition = get_recipe_nutrition(conn, recipe_id, base_servings)

st.subheader(name)
st.write(f"**Meal type:** {meal_type.title()} &nbsp;&nbsp; **Servings:** {base_servings}")

cols = st.columns(5)
cols[0].metric("Calories", f"{nutrition['kcal']:.0f} kcal")
cols[1].metric("Protein", f"{nutrition['protein']:.1f} g")
cols[2].metric("Carbs", f"{nutrition['carbs']:.1f} g")
cols[3].metric("Fat", f"{nutrition['fat']:.1f} g")
cols[4].metric("Fibre", f"{nutrition['fibre']:.1f} g")

method = conn.execute("SELECT method FROM recipes WHERE id = ?", (recipe_id,)).fetchone()[0]

st.divider()
st.markdown("**Ingredients**")
for display_quantity, display_unit, ing_name, quantity_g in conn.execute(
    """
    SELECT ri.display_quantity, ri.display_unit, i.name, ri.quantity_g
    FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id
    WHERE ri.recipe_id = ?
    """,
    (recipe_id,),
):
    st.write(f"- {ingredient_line(display_quantity, display_unit, ing_name, quantity_g)}")

st.markdown("**Method**")
st.write(method or "_No method recorded yet._")

conn.close()
