import json
import sqlite3
from pathlib import Path

import streamlit as st

from calculations import CALORIES_PER_G_CARB, CALORIES_PER_G_FAT, CALORIES_PER_G_PROTEIN

DB_PATH = Path(__file__).parent.parent / "database" / "mealplan.db"

st.set_page_config(page_title="Edit Client", page_icon="✏️")
st.title("✏️ Edit Client Targets")
st.caption(
    "Update a client's current weight and directly adjust their calorie target and "
    "macro split — for example to override the calculated defaults with your own "
    "clinical judgement, without needing to touch activity level, protein g/kg, etc. "
    "on the Add Client page."
)


def get_connection():
    return sqlite3.connect(DB_PATH)


conn = get_connection()
clients = conn.execute("SELECT id, name FROM clients ORDER BY name").fetchall()

if not clients:
    st.info("No clients yet — add one on the **Add Client** page first.")
else:
    client_names = [c[1] for c in clients]
    selected_name = st.selectbox("Client", client_names)
    client_id = next(c[0] for c in clients if c[1] == selected_name)

    row = conn.execute(
        """
        SELECT calorie_target, macro_targets, goal, activity_level,
               fat_percentage_min, fat_percentage_max, weight_kg, has_blender
        FROM clients WHERE id = ?
        """,
        (client_id,),
    ).fetchone()
    (
        calorie_target, macro_targets_json, goal, activity_level,
        fat_percentage_min, fat_percentage_max, weight_kg, has_blender,
    ) = row
    macros = json.loads(macro_targets_json) if macro_targets_json else {"protein_g": 0, "fat_g": 0, "carbs_g": 0}

    st.caption(f"Goal: {(goal or '—').replace('_', ' ').title()} · Activity: {(activity_level or '—').replace('_', ' ').title()}")

    # Plain widgets rather than st.form — the "adds up to X kcal" hint below needs to
    # update live as each number is typed, and fields inside st.form only rerun on submit.
    new_weight_kg = st.number_input(
        "Current weight (kg)", min_value=30.0, max_value=250.0, value=float(weight_kg), step=0.5
    )
    st.caption("Update this as the client's weight changes over the course of their plan.")

    new_has_blender = st.checkbox(
        "Has a blender", value=bool(has_blender),
        help="Unchecking excludes recipes that need a blender/food processor (e.g. smoothies, blended soups).",
    )

    new_calorie_target = st.number_input(
        "Calorie target (kcal)", min_value=800, max_value=6000, value=int(calorie_target), step=10
    )
    col1, col2, col3 = st.columns(3)
    new_protein_g = col1.number_input("Protein (g)", min_value=0.0, value=float(macros["protein_g"]), step=1.0)
    new_fat_g = col2.number_input("Fat (g)", min_value=0.0, value=float(macros["fat_g"]), step=1.0)
    new_carbs_g = col3.number_input("Carbs (g)", min_value=0.0, value=float(macros["carbs_g"]), step=1.0)

    protein_kcal = new_protein_g * CALORIES_PER_G_PROTEIN
    fat_kcal = new_fat_g * CALORIES_PER_G_FAT
    carbs_kcal = new_carbs_g * CALORIES_PER_G_CARB
    implied_kcal = protein_kcal + fat_kcal + carbs_kcal

    # Percentages are of the macros' own total (so they always sum to 100%), not of
    # the calorie target above — the two only match once the kcal-delta hint reads ~0.
    protein_pct = protein_kcal / implied_kcal * 100 if implied_kcal else 0
    fat_pct = fat_kcal / implied_kcal * 100 if implied_kcal else 0
    carbs_pct = carbs_kcal / implied_kcal * 100 if implied_kcal else 0

    col1.caption(f"{protein_pct:.0f}% of calories")
    if fat_percentage_min is not None and fat_percentage_max is not None:
        in_range = fat_percentage_min <= fat_pct <= fat_percentage_max
        flag = "✅" if in_range else "⚠️"
        col2.caption(f"{fat_pct:.0f}% of calories {flag} (target {fat_percentage_min:.0f}-{fat_percentage_max:.0f}%)")
    else:
        col2.caption(f"{fat_pct:.0f}% of calories")
    col3.caption(f"{carbs_pct:.0f}% of calories")

    delta = implied_kcal - new_calorie_target
    hint = (
        f"Split: {protein_pct:.0f}% protein · {fat_pct:.0f}% fat · {carbs_pct:.0f}% carbs — "
        f"adds up to {implied_kcal:.0f} kcal ({delta:+.0f} vs the calorie target above)."
    )
    if abs(delta) > 50:
        st.warning(hint)
    else:
        st.caption(hint)

    submitted = st.button("Save changes")

    if submitted:
        updated_macros = {
            "protein_g": round(new_protein_g, 1),
            "fat_g": round(new_fat_g, 1),
            "carbs_g": round(new_carbs_g, 1),
            "fat_percentage_used": macros.get("fat_percentage_used"),
        }
        conn.execute(
            "UPDATE clients SET weight_kg = ?, calorie_target = ?, macro_targets = ?, has_blender = ? WHERE id = ?",
            (new_weight_kg, new_calorie_target, json.dumps(updated_macros), new_has_blender, client_id),
        )
        conn.commit()
        st.success(f"Updated targets for {selected_name}.")

conn.close()
