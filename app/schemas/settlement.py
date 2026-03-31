from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CreateSettlementRequest(BaseModel):
    fromUserId: UUID
    toUserId: UUID
    currency: str = "USD"
    amount: Decimal
    settlementDate: date
    note: Optional[str] = None


class SettlementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    settlementId: UUID
    groupId: UUID
    fromUserId: UUID
    toUserId: UUID
    currency: str
    amount: Decimal
    settlementDate: date
    note: Optional[str] = None
    createdBy: UUID
    createdAt: datetime

    @classmethod
    def from_orm_model(cls, settlement) -> "SettlementResponse":
        return cls(
            settlementId=settlement.id,
            groupId=settlement.group_id,
            fromUserId=settlement.from_user_id,
            toUserId=settlement.to_user_id,
            currency=settlement.currency,
            amount=settlement.amount,
            settlementDate=settlement.settlement_date,
            note=settlement.note,
            createdBy=settlement.created_by,
            createdAt=settlement.created_at,
        )


class SettlementListResponse(BaseModel):
    settlements: List[SettlementResponse]
    total: int
