from pydantic import BaseModel, Field
from typing import List, Optional


class BookBase(BaseModel):
    book_id: str = Field(..., alias="book_id", min_length=1, max_length=20)
    authorId:str
    title: str = Field(..., min_length=1, max_length=200)
    isbn: str = Field(..., min_length=1, max_length=20)
    genre: str = Field(..., min_length=1, max_length=80)
    publication_date: str
    status: str = Field(..., min_length=1, max_length=50)
    mrp: float = Field(..., ge=0)
    author_royalty_per_copy: float = Field(..., ge=0)
    total_copies_sold: int = Field(..., ge=0)
    total_royalty_earned: float = Field(..., ge=0)
    royalty_paid: float = Field(..., ge=0)
    royalty_pending: float = Field(..., ge=0)
    last_royalty_payout_date: Optional[str] = None
    print_partner: str = Field(..., min_length=1, max_length=50)
    available_on: List[str] = Field(..., min_items=1)

class BookCreateRequest(BookBase):
    pass

class BookResponse(BookBase):
    pass
