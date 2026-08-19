from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    """
    A person changing their own password.

    Separate from `UserUpdate` because it is a different act by a different
    person: an admin setting somebody else's password is a reset, and this is
    somebody proving they already know the current one. Requiring the old
    password is what stops a session left open on the counter from becoming a
    permanent account takeover.
    """

    current_password: str
    new_password: str = Field(min_length=6, max_length=100)
