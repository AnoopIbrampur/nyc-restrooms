"""Category harmonization for Phase 3.

Every place gets a fine class (OSM-style "key=value") and one of eight audit/model groups.
Restaurants found only in DOHMH get a fine class from their cuisine (CUISINE_CLASS).
Places outside the eight groups are excluded from the Phase 3 universe (parks,
playgrounds, places of worship, Refuge-only records, untyped features).
"""

from __future__ import annotations

import pandas as pd

# DOHMH cuisine -> OSM-like fine class (anything not listed -> amenity=restaurant)
CUISINE_CLASS = {
    # cafes, bakeries, desserts, drinks
    **dict.fromkeys(
        [
            "Coffee/Tea", "Bakery Products/Desserts", "Donuts", "Juice, Smoothies, Fruit Salads",
            "Frozen Desserts", "Bagels/Pretzels", "Pancakes/Waffles", "Nuts/Confectionary",
            "Bottled Beverages",
        ],
        "amenity=cafe",
    ),
    # quick service
    **dict.fromkeys(
        [
            "Pizza", "Chicken", "Hamburgers", "Sandwiches", "Sandwiches/Salads/Mixed Buffet",
            "Salads", "Soups/Salads/Sandwiches", "Soups", "Hotdogs", "Hotdogs/Pretzels", "Tex-Mex",
        ],
        "amenity=fast_food",
    ),
    "Fruits/Vegetables": "shop=greengrocer",
}  # fmt: skip

GROUPS = (
    "restaurant",
    "quick_service",
    "cafe_bakery",
    "bar",
    "grocery",
    "retail",
    "services_health",
    "lodging_culture_civic",
)

_GROUP_OF = {
    "restaurant": {"amenity=restaurant", "amenity=food_court"},
    "quick_service": {"amenity=fast_food"},
    "cafe_bakery": {
        "amenity=cafe", "amenity=ice_cream", "shop=bakery", "shop=pastry", "shop=confectionery",
        "shop=coffee", "shop=tea", "shop=chocolate",
    },
    "bar": {"amenity=bar", "amenity=pub", "amenity=nightclub", "amenity=biergarten"},
    "grocery": {
        "shop=supermarket", "shop=convenience", "shop=deli", "shop=alcohol", "shop=greengrocer",
        "shop=variety_store", "shop=butcher", "shop=seafood", "shop=beverages", "shop=wine",
        "shop=health_food", "shop=frozen_food", "shop=farm", "shop=general", "shop=kiosk",
    },
    "services_health": {
        "shop=hairdresser", "shop=beauty", "shop=laundry", "shop=dry_cleaning", "shop=massage",
        "shop=tattoo", "shop=car_repair", "shop=nail_salon", "shop=cosmetics",
        "amenity=clinic", "amenity=doctors", "amenity=dentist", "amenity=pharmacy",
        "amenity=bank", "amenity=veterinary", "amenity=fuel", "amenity=money_transfer",
        "amenity=car_rental", "amenity=bureau_de_change", "amenity=post_office",
        "leisure=fitness_centre", "leisure=sports_centre", "amenity=hospital",
        "amenity=social_facility", "amenity=childcare",
    },
    "lodging_culture_civic": {
        "tourism=hotel", "tourism=motel", "tourism=hostel", "tourism=guest_house",
        "tourism=museum", "tourism=gallery", "tourism=attraction", "tourism=zoo",
        "tourism=aquarium", "tourism=theme_park", "amenity=library", "amenity=theatre",
        "amenity=cinema", "amenity=arts_centre", "amenity=community_centre",
        "amenity=events_venue", "amenity=townhall", "amenity=courthouse",
        "amenity=university", "amenity=college", "leisure=bowling_alley",
        "leisure=amusement_arcade", "leisure=ice_rink", "leisure=stadium",
        "leisure=indoor_play", "leisure=escape_game", "leisure=dance", "amenity=studio",
    },
}  # fmt: skip
_FINE_TO_GROUP = {fine: g for g, fines in _GROUP_OF.items() for fine in fines}


def fine_class(category: str, cuisine: object) -> str:
    if category == "dohmh_restaurant":
        return CUISINE_CLASS.get(cuisine, "amenity=restaurant")
    return category


def group_of(fine: str) -> str | None:
    if fine in _FINE_TO_GROUP:
        return _FINE_TO_GROUP[fine]
    if fine.startswith("shop="):
        return "retail"  # any other shop
    return None


def harmonize(p: pd.DataFrame) -> pd.DataFrame:
    """Adds fine_class and group columns (group is None outside the Phase 3 universe)."""
    out = p.copy()
    out["fine_class"] = [
        fine_class(c, z) for c, z in zip(out["category"], out["dohmh_cuisine"], strict=True)
    ]
    out["group"] = out["fine_class"].map(group_of)
    known = out["official_present"] | out["category"].isin(["amenity=toilets"])
    out.loc[known, "group"] = None
    return out


def cuisine_agreement(p: pd.DataFrame) -> dict:
    """On DOHMH<->OSM matched places: does the cuisine-derived group equal the OSM group?"""
    m = p[p["camis"].notna() & p["place_id"].str.startswith("osm:")]
    osm_g = m["category"].map(group_of)
    dohmh_g = m["dohmh_cuisine"].map(lambda z: group_of(CUISINE_CLASS.get(z, "amenity=restaurant")))
    ok = osm_g.notna()
    agree = (osm_g[ok] == dohmh_g[ok]).mean()
    ct = pd.crosstab(dohmh_g[ok], osm_g[ok])
    return {"pairs": int(ok.sum()), "agreement": round(float(agree), 3), "crosstab": ct}
