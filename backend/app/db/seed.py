"""Idempotent reference data seeds: 2-level category taxonomy & global store chains."""

from __future__ import annotations

import re
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.store import StoreChain


def slugify(text: str) -> str:
    expanded = text.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", "-", expanded.strip().lower()).strip("-")
    return cleaned or "item"


class CategoryGroupSeed(TypedDict):
    name: str
    macro_group: str
    icon: str
    children: list[str]


SYSTEM_TAXONOMY: list[CategoryGroupSeed] = [
    {
        "name": "Food & Beverages",
        "macro_group": "food",
        "icon": "utensils",
        "children": [
            "Fruits",
            "Vegetables",
            "Meat",
            "Fish and seafood",
            "Dairy products",
            "Eggs",
            "Bread and bakery",
            "Cereals and grains",
            "Pasta",
            "Canned products",
            "Frozen products",
            "Snacks and sweets",
            "Coffee and tea",
            "Water",
            "Soft drinks",
            "Sauces and condiments",
            "Other food products",
        ],
    },
    {
        "name": "Household Consumables",
        "macro_group": "household",
        "icon": "Layers",
        "children": [
            "Paper towels",
            "Toilet paper",
            "Tissues",
            "Disposable tableware",
            "Food storage bags",
            "Foil and baking paper",
            "Batteries",
            "Other household consumables",
        ],
    },
    {
        "name": "Personal Care & Bathroom",
        "macro_group": "household",
        "icon": "sparkles",
        "children": [
            "Shampoo",
            "Conditioner",
            "Shower gel",
            "Soap",
            "Toothpaste",
            "Toothbrushes",
            "Deodorants",
            "Skin care",
            "Towels",
            "Bathrobes",
            "Bathroom accessories",
            "Other personal care products",
        ],
    },
    {
        "name": "Cleaning Products & Accessories",
        "macro_group": "household",
        "icon": "spray-can",
        "children": [
            "Laundry detergents",
            "Fabric softeners",
            "Dishwashing detergents",
            "Surface cleaners",
            "Bathroom cleaners",
            "Disinfectants",
            "Sponges",
            "Cleaning cloths",
            "Mops",
            "Brushes",
            "Buckets",
            "Other cleaning accessories",
        ],
    },
    {
        "name": "Household Goods & Accessories",
        "macro_group": "household",
        "icon": "home",
        "children": [
            "Kitchen accessories",
            "Storage containers",
            "Kitchen utensils",
            "Tableware",
            "Home organization products",
            "Household textiles",
            "Other household goods",
        ],
    },
    {
        "name": "Small Household Appliances",
        "macro_group": "household",
        "icon": "plug",
        "children": [
            "Kettles",
            "Toasters",
            "Blenders",
            "Coffee machines",
            "Irons",
            "Vacuum cleaners",
            "Other small appliances",
        ],
    },
]


class StoreChainSeed(TypedDict):
    slug: str
    canonical_name: str
    country: str | None
    aliases: list[str]
    is_fallback: bool


GLOBAL_STORE_CHAINS: list[StoreChainSeed] = [
    # Romanian chains (primary blueprint examples)
    {
        "slug": "lidl",
        "canonical_name": "Lidl",
        "country": "RO",
        "aliases": ["lidl", "lidl discount", "lidl romania", "sc lidl discount srl"],
        "is_fallback": False,
    },
    {
        "slug": "kaufland",
        "canonical_name": "Kaufland",
        "country": "RO",
        "aliases": ["kaufland", "kaufland romania", "kaufland romania scs"],
        "is_fallback": False,
    },
    {
        "slug": "carrefour",
        "canonical_name": "Carrefour",
        "country": "RO",
        "aliases": ["carrefour", "carrefour market", "carrefour express", "carrefour romania"],
        "is_fallback": False,
    },
    {
        "slug": "auchan",
        "canonical_name": "Auchan",
        "country": "RO",
        "aliases": ["auchan", "auchan romania", "myauchan", "ашан"],
        "is_fallback": False,
    },
    {
        "slug": "penny",
        "canonical_name": "Penny",
        "country": "RO",
        "aliases": ["penny", "penny market", "rewe romania"],
        "is_fallback": False,
    },
    {
        "slug": "mega-image",
        "canonical_name": "Mega Image",
        "country": "RO",
        "aliases": ["mega image", "shop & go", "shop and go"],
        "is_fallback": False,
    },
    # Ukrainian chains
    {
        "slug": "atb",
        "canonical_name": "ATB Market",
        "country": "UA",
        "aliases": ["atb", "атб", "атб-маркет", "тов атб-маркет"],
        "is_fallback": False,
    },
    {
        "slug": "silpo",
        "canonical_name": "Silpo",
        "country": "UA",
        "aliases": ["silpo", "сільпо", "сильпо", "тов сільпо-фуд"],
        "is_fallback": False,
    },
    {
        "slug": "novus",
        "canonical_name": "Novus",
        "country": "UA",
        "aliases": ["novus", "новус", "тов новус україна"],
        "is_fallback": False,
    },
    {
        "slug": "metro",
        "canonical_name": "Metro Cash & Carry",
        "country": "RO",
        "aliases": ["metro", "метро", "metro cash & carry"],
        "is_fallback": False,
    },
    {
        "slug": "varus",
        "canonical_name": "Varus",
        "country": "UA",
        "aliases": ["varus", "варус"],
        "is_fallback": False,
    },
    {
        "slug": "fora",
        "canonical_name": "Fora",
        "country": "UA",
        "aliases": ["fora", "фора", "тов фора"],
        "is_fallback": False,
    },
    {
        "slug": "epicentr",
        "canonical_name": "Epicentr K",
        "country": "UA",
        "aliases": ["epicentr", "епіцентр", "епіцентр к"],
        "is_fallback": False,
    },
    # Fallback chain for unknown / local stores (keeps store_chain_id NOT NULL)
    {
        "slug": "other",
        "canonical_name": "Other / Independent Store",
        "country": None,
        "aliases": ["other", "independent", "local store"],
        "is_fallback": True,
    },
]


async def seed_reference_data(session: AsyncSession) -> None:
    """Idempotently populate system categories and global store chains."""
    existing_cats = {
        c.slug: c
        for c in (await session.scalars(select(Category).where(Category.is_system.is_(True)))).all()
    }

    for group in SYSTEM_TAXONOMY:
        root_slug = slugify(group["name"])
        root = existing_cats.get(root_slug)
        if root is None:
            root = Category(
                parent_id=None,
                user_id=None,
                is_system=True,
                macro_group=group["macro_group"],
                name=group["name"],
                slug=root_slug,
                icon=group["icon"],
                is_active=True,
            )
            session.add(root)
            await session.flush()
            existing_cats[root_slug] = root

        for child_name in group["children"]:
            child_slug = slugify(child_name)
            if child_slug not in existing_cats:
                child = Category(
                    parent_id=root.id,
                    user_id=None,
                    is_system=True,
                    macro_group=group["macro_group"],
                    name=child_name,
                    slug=child_slug,
                    is_active=True,
                )
                session.add(child)
                existing_cats[child_slug] = child

    existing_chains = {c.slug: c for c in (await session.scalars(select(StoreChain))).all()}
    for chain_seed in GLOBAL_STORE_CHAINS:
        if chain_seed["slug"] not in existing_chains:
            session.add(
                StoreChain(
                    slug=chain_seed["slug"],
                    canonical_name=chain_seed["canonical_name"],
                    normalized_name=chain_seed["canonical_name"].lower(),
                    aliases=chain_seed["aliases"],
                    country=chain_seed["country"],
                    is_fallback=chain_seed["is_fallback"],
                )
            )

    await session.commit()
