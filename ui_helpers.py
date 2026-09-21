import json
import re

import streamlit as st


def ingredient_line(display_quantity, display_unit, ing_name, quantity_g):
    """Builds one human-readable ingredient line.

    display_quantity/display_unit were hand-curated per recipe and aren't consistent
    across the DB: some rows already spell out the food ("g brown pasta spirals, raw
    weight"), others hold only a bare unit ("cup", "tbsp") with no food word at all.
    Rather than always appending the ingredient's DB name (redundant for the first
    style) or never appending it (blank for the second), check whether the food's own
    name is already present in the display phrase and only add it when it's missing.
    """
    phrase = " ".join(part for part in [display_quantity, display_unit] if part)
    if not phrase:
        return f"{quantity_g:.0f} g {ing_name}"

    # Check the whole ingredient name, not just the text before the first comma —
    # for names like "Spices, cinnamon, ground" the actual food word (cinnamon) comes
    # after the comma, so checking only the leading segment ("Spices") misses it.
    words = [w for w in re.findall(r"[A-Za-z]+", ing_name) if len(w) >= 4]
    already_named = any(w.lower() in phrase.lower() for w in words) if words else False

    return phrase if already_named else f"{phrase} {ing_name}"


@st.dialog("Recipe", width="large")
def show_recipe(conn, recipe_id):
    """Modal popup with a recipe's full ingredient list and method."""
    name, method, base_servings, batch_cook_suitable, dietary_tags_json = conn.execute(
        "SELECT name, method, base_servings, batch_cook_suitable, dietary_tags FROM recipes WHERE id = ?",
        (recipe_id,),
    ).fetchone()

    st.subheader(name)

    badges = []
    if batch_cook_suitable:
        badges.append("🧊 Batch-cook suitable")
    tags = json.loads(dietary_tags_json) if dietary_tags_json else {}
    for suitable in tags.get("suitable_for", []):
        badges.append(f"✅ {suitable}")
    if badges:
        st.caption(" · ".join(badges))

    st.caption(f"Makes {base_servings} serving(s)")

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


def recipe_link_button(conn, recipe_id, label, key):
    """Button styled as a link that opens the recipe detail dialog when clicked."""
    if st.button(label, key=key, type="tertiary"):
        show_recipe(conn, recipe_id)
