"""BMR, TDEE, and macro target calculations.

Kept separate from the Streamlit pages so the math can be tested and reused
independently of the UI.
"""

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "lightly_active": 1.375,
    "moderately_active": 1.55,
    "very_active": 1.725,
    "extra_active": 1.9,
}

# Training-session guidance per level, shown alongside the multiplier in the client
# intake form so the professional can pick a level from what the client actually does,
# rather than guessing what "lightly active" is supposed to mean.
ACTIVITY_DESCRIPTIONS = {
    "sedentary": "little or no exercise",
    "lightly_active": "light exercise/sport 1-3 days/week",
    "moderately_active": "moderate exercise/sport 3-5 days/week",
    "very_active": "hard exercise/sport 6-7 days/week",
    "extra_active": "very hard exercise or training twice a day",
}

CALORIES_PER_G_PROTEIN = 4
CALORIES_PER_G_CARB = 4
CALORIES_PER_G_FAT = 9


def calculate_bmr(equation, weight_kg, height_cm, age, gender, body_fat_percentage=None):
    """Returns BMR in kcal/day."""
    if equation == "mifflin_st_jeor":
        base = 10 * weight_kg + 6.25 * height_cm - 5 * age
        return base + 5 if gender == "male" else base - 161

    if equation == "katch_mcardle":
        if body_fat_percentage is None:
            raise ValueError("Katch-McArdle requires body_fat_percentage")
        lean_body_mass_kg = weight_kg * (1 - body_fat_percentage / 100)
        return 370 + 21.6 * lean_body_mass_kg

    raise ValueError(f"Unknown BMR equation: {equation}")


def calculate_calorie_target(bmr, activity_level):
    """TDEE = BMR x activity multiplier."""
    return bmr * ACTIVITY_MULTIPLIERS[activity_level]


def calculate_macros(calorie_target, weight_kg, protein_g_per_kg, fat_percentage_min, fat_percentage_max):
    """Protein first (g/kg), fat as a % of total calories (midpoint of the given
    range), carbs as the remainder. Returns grams for each plus the fat % used.
    """
    protein_g = protein_g_per_kg * weight_kg
    protein_kcal = protein_g * CALORIES_PER_G_PROTEIN

    fat_percentage_used = (fat_percentage_min + fat_percentage_max) / 2
    fat_kcal = calorie_target * (fat_percentage_used / 100)
    fat_g = fat_kcal / CALORIES_PER_G_FAT

    carb_kcal = calorie_target - protein_kcal - fat_kcal
    carb_g = carb_kcal / CALORIES_PER_G_CARB

    return {
        "protein_g": round(protein_g, 1),
        "fat_g": round(fat_g, 1),
        "carbs_g": round(carb_g, 1),
        "fat_percentage_used": fat_percentage_used,
    }
