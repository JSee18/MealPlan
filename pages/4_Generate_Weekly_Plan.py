import sqlite3
from pathlib import Path

import streamlit as st

from generator import generate_weekly_plan, generate_shopping_list
from pdf_export import build_weekly_plan_pdf
from ui_helpers import recipe_link_button

MEAL_TYPE_CHOICES = ["breakfast", "lunch", "dinner", "snack"]

DB_PATH = Path(__file__).parent.parent / "database" / "mealplan.db"

st.set_page_config(page_title="Generate Weekly Plan", page_icon="📅", layout="wide")
st.title("📅 Generate a 7-Day Plan")
st.caption(
    "Batch-suitable recipes can repeat up to 3 days by default (relaxed only if there aren't "
    "enough recipes to fill the week); recipes not marked batch-suitable appear at most once."
)


def get_connection():
    return sqlite3.connect(DB_PATH)


conn = get_connection()
clients = conn.execute("SELECT id, name FROM clients ORDER BY name").fetchall()

if not clients:
    st.info("No clients yet - add one on the **Add Client** page first.")
else:
    client_names = [c[1] for c in clients]
    selected_name = st.selectbox("Client", client_names)
    client_id = next(c[0] for c in clients if c[1] == selected_name)

    if st.button("Generate 7-day plan"):
        try:
            st.session_state["weekly_plan"] = generate_weekly_plan(conn, client_id)
        except ValueError as e:
            st.session_state.pop("weekly_plan", None)
            st.error(str(e))

    plan = st.session_state.get("weekly_plan")
    # Stored in session_state (rather than a plain local variable) so the plan survives the
    # rerun triggered by clicking a recipe-detail button below — otherwise that rerun would
    # skip this button's now-False click check and the whole plan would vanish.
    if plan:
        st.subheader(f"Plan for {plan['client_name']}")

        if plan["notes"]:
            for note in plan["notes"]:
                st.warning(note)

        t = plan["targets"]
        st.caption(
            f"Daily target: {t['calorie_target']:.0f} kcal | {t['protein_g']:.0f}g protein | "
            f"{t['carbs_g']:.0f}g carbs | {t['fat_g']:.0f}g fat | {t['fibre_g']:.0f}g fibre"
        )

        shopping = generate_shopping_list(conn, plan)
        with st.expander(f"🛒 Shopping list ({len(shopping['items'])} items)", expanded=True):
            st.caption(
                "Aggregated across the full week — batch-cooked recipes are only bought "
                "enough times to cover how many times they're actually cooked, not how "
                "many times they're eaten."
            )

            def render_grouped(grouped):
                group_cols = st.columns(2)
                for i, group in enumerate(grouped):
                    with group_cols[i % 2]:
                        st.markdown(f"**{group['category']}** _{len(group['items'])} item(s)_")
                        for item in group["items"]:
                            st.write(f"- {item['display']} {item['name']}")
                        st.write("")

            main_item_count = sum(len(g["items"]) for g in shopping["grouped_main"])
            side_item_count = sum(len(g["items"]) for g in shopping["grouped_sides"])
            main_tab, sides_tab = st.tabs([
                f"For Your Meals ({main_item_count} items)",
                f"Sides & Extras ({side_item_count} items)",
            ])
            with main_tab:
                st.caption("Everything needed for the breakfast/lunch/dinner/snack recipes themselves.")
                render_grouped(shopping["grouped_main"])
            with sides_tab:
                st.caption("Only needed for the extra veg/fruit/protein sides — nothing here is double-counted with the meals tab.")
                render_grouped(shopping["grouped_sides"])

            st.caption("Recipes this week (times cooked, not times eaten):")
            for r in shopping["recipes_used"]:
                cook_note = f", cooked {r['times_to_cook']}x" if r['times_to_cook'] != r['times_used'] else ""
                recipe_link_button(
                    conn, r["recipe_id"], f"{r['name']} — eaten {r['times_used']}x{cook_note}",
                    key=f"shoplist_recipe_{r['recipe_id']}",
                )

        day_tabs = st.tabs([f"Day {d['day']}" for d in plan["days"]])
        for tab, day in zip(day_tabs, plan["days"]):
            with tab:
                tot = day["totals"]
                cols = st.columns(5)
                cols[0].metric("Calories", f"{tot['kcal']:.0f} kcal", f"{tot['kcal'] - t['calorie_target']:.0f} vs target")
                cols[1].metric("Protein", f"{tot['protein']:.0f} g", f"{tot['protein'] - t['protein_g']:.0f} vs target")
                cols[2].metric("Carbs", f"{tot['carbs']:.0f} g", f"{tot['carbs'] - t['carbs_g']:.0f} vs target")
                cols[3].metric("Fat", f"{tot['fat']:.0f} g", f"{tot['fat'] - t['fat_g']:.0f} vs target")
                cols[4].metric("Fibre", f"{tot['fibre']:.0f} g", f"{tot['fibre'] - t['fibre_g']:.0f} vs target")

                for meal in day["meals"]:
                    with st.container(border=True):
                        if meal["meal_type"] == "side":
                            st.caption(f"+ Side, with {meal['paired_with'].title()}")
                        else:
                            st.caption(meal["meal_type"].title())
                        recipe_link_button(
                            conn, meal["recipe_id"], meal["name"],
                            key=f"day{day['day']}_recipe_{meal['recipe_id']}",
                        )
                        st.caption(
                            f"{meal['kcal']:.0f} kcal · {meal['protein']:.1f}g protein · "
                            f"{meal['carbs']:.1f}g carbs · {meal['fat']:.1f}g fat · {meal['fibre']:.1f}g fibre"
                        )

        st.divider()
        st.subheader("📄 PDF Export")
        st.caption(
            "Shopping list on page 1, then each day's meal summary followed by the full "
            "recipes needed that day. Choose the order breakfast/lunch/dinner/snack appear "
            "within each day below."
        )
        order_cols = st.columns(4)
        position_labels = ["1st", "2nd", "3rd", "4th"]
        chosen_order = [
            col.selectbox(label, MEAL_TYPE_CHOICES, index=i, key=f"pdf_order_{i}", format_func=str.title)
            for i, (col, label) in enumerate(zip(order_cols, position_labels))
        ]

        if st.button("Generate PDF"):
            # De-dupe while preserving the chosen order (a client could pick the same meal
            # type for two positions by mistake), then append anything left out so nothing
            # from the plan silently goes missing from the PDF.
            meal_type_order = []
            for mt in chosen_order + MEAL_TYPE_CHOICES:
                if mt not in meal_type_order:
                    meal_type_order.append(mt)
            st.session_state["weekly_plan_pdf"] = build_weekly_plan_pdf(conn, plan, shopping, meal_type_order)

        if "weekly_plan_pdf" in st.session_state:
            st.download_button(
                "⬇️ Download PDF",
                data=st.session_state["weekly_plan_pdf"],
                file_name=f"{plan['client_name'].replace(' ', '_')}_weekly_plan.pdf",
                mime="application/pdf",
            )

conn.close()
