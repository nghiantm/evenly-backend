import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.group import Group
    from app.models.user import User
    from app.models.settlement import Settlement


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="expenses")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    payments: Mapped[List["ExpensePayment"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )
    splits: Mapped[List["ExpenseSplit"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )
    transfers: Mapped[List["GroupTransfer"]] = relationship(
        back_populates="expense",
        foreign_keys="GroupTransfer.expense_id",
    )


class ExpensePayment(Base):
    __tablename__ = "expense_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id"), nullable=False, index=True
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="payments")
    payer: Mapped["User"] = relationship(foreign_keys=[payer_id])


class ExpenseSplit(Base):
    __tablename__ = "expense_splits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    amount_owed: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    split_type: Mapped[str] = mapped_column(String(20), default="EQUAL")
    shares: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="splits")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class GroupTransfer(Base):
    __tablename__ = "group_transfers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id"), nullable=False, index=True
    )
    expense_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("expenses.id"), nullable=True, index=True
    )
    settlement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("settlements.id"), nullable=True, index=True
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="transfers")
    expense: Mapped[Optional["Expense"]] = relationship(
        back_populates="transfers", foreign_keys=[expense_id]
    )
    settlement: Mapped[Optional["Settlement"]] = relationship(
        back_populates="transfers", foreign_keys=[settlement_id]
    )
    from_user: Mapped["User"] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped["User"] = relationship(foreign_keys=[to_user_id])
