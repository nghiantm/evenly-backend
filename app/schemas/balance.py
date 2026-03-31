from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel


class UserBalance(BaseModel):
    userId: UUID
    displayName: str
    netAmount: Decimal


class PairwiseDebt(BaseModel):
    fromUserId: UUID
    toUserId: UUID
    amount: Decimal
    currency: str


class GroupBalanceResponse(BaseModel):
    groupId: UUID
    currency: str
    userBalances: List[UserBalance]
    pairwiseDebts: List[PairwiseDebt]


class MyBalancesResponse(BaseModel):
    youOwe: Decimal
    youAreOwed: Decimal
    netByGroup: List[Dict[str, Any]]
    netByUser: List[Dict[str, Any]]
