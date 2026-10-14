from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)