from pydantic import BaseModel, Field


class BookCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    isbn: str = Field(min_length=1, max_length=20)
    genre: str = Field(min_length=1, max_length=80)
    mrp: float = Field(ge=0)
    publicationDate: str | None = None
