from enum import Enum

class BudgetType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"

class RepeatUnit(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
