from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CreateGroupRequest(BaseModel):
    name: str
    defaultCurrency: str = "USD"


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    defaultCurrency: Optional[str] = None
    simplifyDebts: Optional[bool] = None


class AddMemberRequest(BaseModel):
    userId: UUID
    role: str = "MEMBER"


class GroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    userId: UUID
    email: str
    displayName: str
    role: str
    joinedAt: datetime

    @classmethod
    def from_orm_model(cls, member) -> "GroupMemberResponse":
        return cls(
            userId=member.user_id,
            email=member.user.email,
            displayName=member.user.display_name,
            role=member.role,
            joinedAt=member.joined_at,
        )


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    groupId: UUID
    name: str
    defaultCurrency: str
    simplifyDebts: bool
    createdAt: datetime
    updatedAt: datetime
    archivedAt: Optional[datetime] = None
    memberCount: int
    myRole: str

    @classmethod
    def from_orm_model(cls, group, my_role: str, member_count: int) -> "GroupResponse":
        return cls(
            groupId=group.id,
            name=group.name,
            defaultCurrency=group.default_currency,
            simplifyDebts=group.simplify_debts,
            createdAt=group.created_at,
            updatedAt=group.updated_at,
            archivedAt=group.archived_at,
            memberCount=member_count,
            myRole=my_role,
        )


class GroupDetailResponse(GroupResponse):
    members: List[GroupMemberResponse] = []
    recentExpenseCount: int = 0
    recentSettlementCount: int = 0

    @classmethod
    def from_orm_model_detail(
        cls,
        group,
        my_role: str,
        member_count: int,
        members: List[GroupMemberResponse],
        recent_expense_count: int,
        recent_settlement_count: int,
    ) -> "GroupDetailResponse":
        return cls(
            groupId=group.id,
            name=group.name,
            defaultCurrency=group.default_currency,
            simplifyDebts=group.simplify_debts,
            createdAt=group.created_at,
            updatedAt=group.updated_at,
            archivedAt=group.archived_at,
            memberCount=member_count,
            myRole=my_role,
            members=members,
            recentExpenseCount=recent_expense_count,
            recentSettlementCount=recent_settlement_count,
        )
