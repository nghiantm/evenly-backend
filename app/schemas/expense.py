from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

ALLOWED_CATEGORIES = {
    "food & drink",
    "groceries",
    "transport",
    "accommodation",
    "entertainment",
    "utilities",
    "healthcare",
    "shopping",
    "travel",
    "education",
    "fitness & sports",
    "personal care",
    "fees & charges",
    "other",
}


class ExpensePayerInput(BaseModel):
    userId: UUID
    amount: Decimal


class ExpenseSplitInput(BaseModel):
    userId: UUID
    amountOwed: Decimal
    splitType: str = "EXACT"
    shares: Optional[Decimal] = None
    percentage: Optional[Decimal] = None

    @field_validator("splitType")
    @classmethod
    def validate_split_type(cls, v: str) -> str:
        allowed = {"EQUAL", "EXACT", "PERCENT", "SHARE"}
        if v not in allowed:
            raise ValueError(f"splitType must be one of {allowed}")
        return v


def _validate_category(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in ALLOWED_CATEGORIES:
        raise ValueError(f"category must be one of {sorted(ALLOWED_CATEGORIES)}")
    return v


class CreateExpenseRequest(BaseModel):
    groupId: UUID
    description: str
    currency: str = "USD"
    totalAmount: Decimal
    expenseDate: date
    note: Optional[str] = None
    category: Optional[str] = None
    paidBy: List[ExpensePayerInput]
    splits: List[ExpenseSplitInput]

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        return _validate_category(v)


class UpdateExpenseRequest(BaseModel):
    description: Optional[str] = None
    currency: Optional[str] = None
    totalAmount: Optional[Decimal] = None
    expenseDate: Optional[date] = None
    note: Optional[str] = None
    category: Optional[str] = None
    paidBy: Optional[List[ExpensePayerInput]] = None
    splits: Optional[List[ExpenseSplitInput]] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        return _validate_category(v)


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    expenseId: UUID
    groupId: UUID
    description: str
    currency: str
    exchangeRate: Decimal
    totalAmount: Decimal
    convertedAmount: Decimal
    expenseDate: date
    note: Optional[str] = None
    category: Optional[str] = None
    createdBy: UUID
    paidBy: List[Dict[str, Any]] = []
    splits: List[Dict[str, Any]] = []
    createdAt: datetime
    updatedAt: datetime

    @classmethod
    def from_orm_model(cls, expense) -> "ExpenseResponse":
        paid_by = [
            {"userId": str(p.payer_id), "amount": float(p.amount)}
            for p in expense.payments
        ]
        splits = [
            {
                "userId": str(s.user_id),
                "amountOwed": float(s.amount_owed),
                "splitType": s.split_type,
                "shares": float(s.shares) if s.shares is not None else None,
                "percentage": float(s.percentage) if s.percentage is not None else None,
            }
            for s in expense.splits
        ]
        exchange_rate = expense.exchange_rate if expense.exchange_rate is not None else Decimal("1")
        return cls(
            expenseId=expense.id,
            groupId=expense.group_id,
            description=expense.description,
            currency=expense.currency,
            exchangeRate=exchange_rate,
            totalAmount=expense.total_amount,
            convertedAmount=(expense.total_amount * exchange_rate).quantize(Decimal("0.01")),
            expenseDate=expense.expense_date,
            note=expense.note,
            category=expense.category,
            createdBy=expense.created_by,
            paidBy=paid_by,
            splits=splits,
            createdAt=expense.created_at,
            updatedAt=expense.updated_at,
        )


class ExpenseListResponse(BaseModel):
    expenses: List[ExpenseResponse]
    total: int
    page: int
    pageSize: int
    totalPages: int
