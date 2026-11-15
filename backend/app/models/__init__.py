"""Export all ORM models so metadata registration and Alembic autogenerate see every table."""

from app.models.agent import AgentAction, AIUsageDaily, Conversation, Message
from app.models.budget import Budget
from app.models.category import Category
from app.models.insight import DashboardInsight
from app.models.product import Product, ProductAlias
from app.models.profile import AppInstallation, Profile
from app.models.purchase import Purchase, PurchaseItem
from app.models.receipt import Receipt
from app.models.shopping_list import ShoppingList, ShoppingListItem
from app.models.store import Store, StoreChain

__all__ = [
    "AIUsageDaily",
    "AgentAction",
    "AppInstallation",
    "Budget",
    "Category",
    "Conversation",
    "DashboardInsight",
    "Message",
    "Product",
    "ProductAlias",
    "Profile",
    "Purchase",
    "PurchaseItem",
    "Receipt",
    "ShoppingList",
    "ShoppingListItem",
    "Store",
    "StoreChain",
]
