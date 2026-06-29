"""Recipe registry — pluggable real-world fulfillment actions.

A recipe is the thing the agent actually delivers after a spend is
authorized: a real external action with real cost. spend.py handles the
authority-band check and the customer-facing Stripe charge (the earn leg);
a recipe handles fulfillment (the spend leg). Adding a new recipe means
adding one file here and one line to RECIPES — nothing else changes.
"""
from . import status_alert

RECIPES = {
    "status_alert": status_alert.execute,
}


def run(recipe_name, **kwargs):
    if recipe_name not in RECIPES:
        raise ValueError(f"Unknown recipe: {recipe_name}. Available: {list(RECIPES)}")
    return RECIPES[recipe_name](**kwargs)
