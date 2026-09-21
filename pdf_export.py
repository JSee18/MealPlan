"""Builds a printable weekly meal plan PDF: the shopping list on page 1, then
each day's meal summary (matching the UI's meal cards) followed by the full
recipes needed that day, so the output is directly cookable without the app
open. Meal type order (which of breakfast/lunch/dinner/snack comes first
within a day) is caller-configurable — see order_meals().
"""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Indenter, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from ui_helpers import ingredient_line

DEFAULT_MEAL_TYPE_ORDER = ["breakfast", "lunch", "dinner", "snack"]

# A small, consistent black-and-red palette rather than default black-on-white
# reportlab output. RED is the accent colour (banners, headings, bullets); BLACK
# ("near-black", easier on the eye than pure #000 for large text areas) is the
# secondary accent (section headers, recipe names) and body text colour.
RED = colors.HexColor("#B01E28")
RED_DARK = colors.HexColor("#7A1015")
BLACK = colors.HexColor("#1A1A1A")
CARD_BG = colors.HexColor("#F7F5F5")
CARD_BORDER = colors.HexColor("#E0DADA")
TEXT_DARK = BLACK
TEXT_MUTED = colors.HexColor("#5A5A5A")
DIVIDER = colors.HexColor("#DDDDDD")


def esc(text):
    """reportlab's Paragraph uses its own mini-markup (like light HTML), not plain
    text, so any recipe/ingredient name pulled from the DB needs escaping before
    being embedded — several recipe names contain a bare "&" (e.g. "Bacon &
    Broccoli Muffins"), which this reportlab version happens to render literally
    today but isn't guaranteed to keep doing, since "&" only means literal text
    there when it doesn't happen to look like the start of an entity reference.
    """
    return escape(str(text))


def _method_paragraph(method, style):
    """Escaped first (see esc()), then real newlines become <br/> - a raw "\n"
    between numbered steps is just whitespace to Paragraph and gets collapsed,
    running every step into one block without this.
    """
    text = esc(method or "No method recorded.")
    return Paragraph(text.replace("\n", "<br/>"), style)


def _effective_type(meal):
    """A side's own "type" for ordering purposes is whichever meal it's paired
    with, not the literal "side" meal_type — so it sorts alongside that meal."""
    return meal["paired_with"] if meal["meal_type"] == "side" else meal["meal_type"]


def order_meals(meals, meal_type_order):
    """Reorders a day's meals to follow meal_type_order, keeping each side
    directly after the meal it's paired with — same grouping the UI uses
    (sort_meals_with_paired_sides in generator.py), just with a caller-chosen
    meal-type sequence instead of the fixed breakfast->lunch->dinner->snack one.
    """
    order_index = {mt: i for i, mt in enumerate(meal_type_order)}
    def key(m):
        return (order_index.get(_effective_type(m), len(meal_type_order)), m["meal_type"] == "side")
    return sorted(meals, key=key)


def _styles():
    base = getSampleStyleSheet()
    return {
        "banner_title": ParagraphStyle(
            "banner_title", parent=base["Title"], textColor=colors.white,
            fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=0, spaceAfter=0,
        ),
        "banner_sub": ParagraphStyle(
            "banner_sub", parent=base["Normal"], textColor=colors.white, fontSize=10, leading=13,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], textColor=BLACK,
            fontName="Helvetica-Bold", fontSize=14, spaceBefore=14, spaceAfter=4, leading=17,
        ),
        "category": ParagraphStyle(
            "category", parent=base["Heading2"], textColor=RED,
            fontName="Helvetica-Bold", fontSize=11, spaceBefore=9, spaceAfter=3, leading=13,
        ),
        "body": ParagraphStyle("body", parent=base["Normal"], textColor=TEXT_DARK, fontSize=9.7, leading=13.5),
        "caption": ParagraphStyle("caption", parent=base["Normal"], textColor=TEXT_MUTED, fontSize=8.7, leading=12),
        "meal_label": ParagraphStyle(
            "meal_label", parent=base["Normal"], textColor=RED,
            fontName="Helvetica-Bold", fontSize=8, leading=10,
        ),
        "side_label": ParagraphStyle(
            "side_label", parent=base["Normal"], textColor=TEXT_MUTED,
            fontName="Helvetica-Bold", fontSize=8, leading=10,
        ),
        "meal_name": ParagraphStyle(
            "meal_name", parent=base["Normal"], textColor=TEXT_DARK,
            fontName="Helvetica-Bold", fontSize=12.5, leading=15,
        ),
        "side_name": ParagraphStyle(
            "side_name", parent=base["Normal"], textColor=TEXT_DARK,
            fontName="Helvetica-Bold", fontSize=11, leading=14,
        ),
        "recipe_name": ParagraphStyle(
            "recipe_name", parent=base["Heading3"], textColor=BLACK,
            fontName="Helvetica-Bold", fontSize=12.5, spaceBefore=10, spaceAfter=2, leading=15,
        ),
    }


def _banner(title, subtitle, styles, width):
    """A black header banner (title + optional subtitle) with a red accent stripe
    across the top, as a single-cell table - used for "Shopping List" and each
    day's heading. Reads far more like a designed document than plain heading
    text on a white page.
    """
    cell = [Paragraph(esc(title), styles["banner_title"])]
    if subtitle:
        cell.append(Spacer(1, 4))
        cell.append(Paragraph(subtitle, styles["banner_sub"]))
    table = Table([[cell]], colWidths=[width])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLACK),
        ("LINEABOVE", (0, 0), (-1, 0), 4, RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


SIDE_CARD_INDENT = 12 * mm  # how far a side card is shifted right of its main meal


def _meal_card(label, name, macros_text, width, styles, is_side=False):
    """One meal's summary as a bordered card with a coloured left accent stripe -
    label, recipe name, then a muted macro line, echoing the bordered containers
    the Streamlit UI already uses for the same information.

    Sides get a visually distinct treatment (Jemma: "highlight the side with a
    separate colour or indent") so it's obvious at a glance which cards are the
    actual meal vs. an attached extra: narrower/indented, a muted black-grey
    accent stripe instead of the mains' red one, smaller name text, and a plain
    white background instead of the mains' light card tint.
    """
    label_style = "side_label" if is_side else "meal_label"
    name_style = "side_name" if is_side else "meal_name"
    accent = TEXT_MUTED if is_side else RED
    card_width = width - SIDE_CARD_INDENT if is_side else width

    content = [
        Paragraph(esc(label).upper(), styles[label_style]),
        Paragraph(esc(name), styles[name_style]),
        Paragraph(macros_text, styles["caption"]),
    ]
    table = Table([[content]], colWidths=[card_width])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white if is_side else CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, CARD_BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7 if is_side else 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7 if is_side else 8),
    ]))
    if is_side:
        return Indenter(left=SIDE_CARD_INDENT), table, Indenter(left=-SIDE_CARD_INDENT)
    return (table,)


def _section_header(text, styles, story):
    """A section heading (e.g. "For Your Meals", "Recipes") with a divider rule
    underneath, in place of a bare heading with nothing to visually anchor it."""
    story.append(Paragraph(text, styles["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=DIVIDER, spaceAfter=6))


def _make_footer(client_name):
    """Returns an onPage callback drawing a running footer: client name + plan
    label on the left, page number on the right, with a thin rule above."""
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(DIVIDER)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 14 * mm, doc.pagesize[0] - 18 * mm, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"{client_name} — 7-Day Meal Plan")
        canvas.drawRightString(doc.pagesize[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def build_weekly_plan_pdf(conn, plan, shopping, meal_type_order=None):
    """Returns the PDF as bytes."""
    meal_type_order = meal_type_order or DEFAULT_MEAL_TYPE_ORDER
    s = _styles()
    client_name = plan["client_name"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=22 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    content_width = doc.width
    footer = _make_footer(client_name)
    story = []

    # --- Page 1: shopping list, split into meals vs. sides/extras (same split as the
    # UI), each grouped by category. Nothing is double-listed - an ingredient used by
    # at least one main recipe is grouped there even if a side also uses it.
    story.append(_banner("Shopping List", esc(client_name), s, content_width))
    story.append(Spacer(1, 14))
    for section_title, grouped in [("For Your Meals", shopping["grouped_main"]), ("Sides & Extras", shopping["grouped_sides"])]:
        if not grouped:
            continue
        _section_header(section_title, s, story)
        for group in grouped:
            story.append(Paragraph(
                f"{esc(group['category'])} "
                f"<font color='#{TEXT_MUTED.hexval()[2:]}' size=8.5>({len(group['items'])} item(s))</font>",
                s["category"],
            ))
            items = [
                ListItem(Paragraph(esc(f"{item['display']} {item['name']}"), s["body"]), bulletColor=RED)
                for item in group["items"]
            ]
            story.append(ListFlowable(items, bulletType="bullet", leftIndent=14))
            story.append(Spacer(1, 3))
    story.append(PageBreak())

    # --- Day by day: meal summary cards, then the full recipes needed that day ---
    t = plan["targets"]
    for day in plan["days"]:
        if day["day"] > 1:
            story.append(PageBreak())

        tot = day["totals"]
        subtitle = (
            f"{tot['kcal']:.0f} kcal ({tot['kcal'] - t['calorie_target']:+.0f} vs target) &nbsp;·&nbsp; "
            f"{tot['protein']:.0f}g protein &nbsp;·&nbsp; {tot['carbs']:.0f}g carbs &nbsp;·&nbsp; "
            f"{tot['fat']:.0f}g fat &nbsp;·&nbsp; {tot['fibre']:.0f}g fibre"
        )
        story.append(_banner(f"Day {day['day']}", subtitle, s, content_width))
        story.append(Spacer(1, 10))

        ordered = order_meals(day["meals"], meal_type_order)

        for meal in ordered:
            is_side = meal["meal_type"] == "side"
            label = f"Side, with {meal['paired_with'].title()}" if is_side else meal["meal_type"].title()
            macros_text = (
                f"{meal['kcal']:.0f} kcal · {meal['protein']:.1f}g protein · {meal['carbs']:.1f}g carbs · "
                f"{meal['fat']:.1f}g fat · {meal['fibre']:.1f}g fibre"
            )
            story.extend(_meal_card(label, meal["name"], macros_text, content_width, s, is_side=is_side))
            story.append(Spacer(1, 6))

        # Recipes start on their own page (Jemma) - each day's own cooking
        # instructions read as a fresh, self-contained section rather than
        # butting straight up against the meal-card summary above.
        story.append(PageBreak())
        _section_header("Recipes", s, story)

        for meal in ordered:
            name, method, base_servings = conn.execute(
                "SELECT name, method, base_servings FROM recipes WHERE id = ?", (meal["recipe_id"],)
            ).fetchone()
            story.append(Paragraph(esc(name), s["recipe_name"]))
            story.append(Paragraph(f"Makes {base_servings} serving(s)", s["caption"]))

            ing_items = [
                ListItem(
                    Paragraph(esc(ingredient_line(display_quantity, display_unit, ing_name, quantity_g)), s["body"]),
                    bulletColor=RED,
                )
                for display_quantity, display_unit, ing_name, quantity_g in conn.execute(
                    """
                    SELECT ri.display_quantity, ri.display_unit, i.name, ri.quantity_g
                    FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id
                    WHERE ri.recipe_id = ?
                    """,
                    (meal["recipe_id"],),
                )
            ]
            story.append(ListFlowable(ing_items, bulletType="bullet", leftIndent=14))
            story.append(Spacer(1, 4))
            story.append(_method_paragraph(method, s["body"]))
            story.append(Spacer(1, 12))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer.getvalue()
