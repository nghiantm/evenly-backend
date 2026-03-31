from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    userId: UUID
    externalSubject: str
    email: str
    displayName: str
    emailVerified: bool
    status: str
    defaultCurrency: str
    avatarUrl: Optional[str] = None

    @classmethod
    def from_orm_model(cls, user) -> "UserProfile":
        return cls(
            userId=user.id,
            externalSubject=user.external_subject,
            email=user.email,
            displayName=user.display_name,
            emailVerified=user.email_verified,
            status=user.status,
            defaultCurrency=user.default_currency,
            avatarUrl=user.avatar_url,
        )


class UpdateUserRequest(BaseModel):
    displayName: Optional[str] = None
    defaultCurrency: Optional[str] = None
    avatarUrl: Optional[str] = None


class UserSearchResult(BaseModel):
    userId: UUID
    email: str
    displayName: str
    avatarUrl: Optional[str] = None

    @classmethod
    def from_orm_model(cls, user) -> "UserSearchResult":
        return cls(
            userId=user.id,
            email=user.email,
            displayName=user.display_name,
            avatarUrl=user.avatar_url,
        )
