import sqlite3
from pathlib import Path

import streamlit as st

from generator import generate_daily_plan
from ui_helpers import recipe_link_button

DB_PATH = Path(__file__).parent.parent / "database" / "mealplan.db"

st.set_page_config(page_title="Generate Plan", page_icon="🍽️", layout="wide")
st.title("🍽️ Generate a Daily Plan")
st.caption("v1 — picks one day's meals/snacks that best hit the client's calorie and macro targets.")


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

    if st.button("Generate plan"):
        try:
            st.session_state["daily_plan"] = generate_daily_plan(conn, client_id)
        except ValueError as e:
            st.session_state.pop("daily_plan", None)
            st.error(str(e))

    plan = st.session_state.get("daily_plan")
    # Kept in session_state so the plan survives the rerun triggered by clicking a
    # recipe-detail button below, instead of vanishing once "Generate plan" is no longer True.
    if plan:
        st.subheader(f"Plan for {plan['client_name']}")

        t, tot = plan["targets"], plan["totals"]
        cols = st.columns(5)
        cols[0].metric("Calories", f"{tot['kcal']:.0f} kcal", f"{tot['kcal'] - t['calorie_target']:.0f} vs target")
        cols[1].metric("Protein", f"{tot['protein']:.0f} g", f"{tot['protein'] - t['protein_g']:.0f} vs target")
        cols[2].metric("Carbs", f"{tot['carbs']:.0f} g", f"{tot['carbs'] - t['carbs_g']:.0f} vs target")
        cols[3].metric("Fat", f"{tot['fat']:.0f} g", f"{tot['fat'] - t['fat_g']:.0f} vs target")
        cols[4].metric("Fibre", f"{tot['fibre']:.0f} g", f"{tot['fibre'] - t['fibre_g']:.0f} vs target")

        st.divider()
        for meal in plan["meals"]:
            with st.container(border=True):
                if meal["meal_type"] == "side":
                    st.caption(f"+ Side, with {meal['paired_with'].title()}")
                else:
                    st.caption(meal["meal_type"].title())
                recipe_link_button(conn, meal["recipe_id"], meal["name"], key=f"recipe_{meal['recipe_id']}")
                st.caption(
                    f"{meal['kcal']:.0f} kcal · {meal['protein']:.1f}g protein · "
                    f"{meal['carbs']:.1f}g carbs · {meal['fat']:.1f}g fat · {meal['fibre']:.1f}g fibre"
                )

conn.close()
