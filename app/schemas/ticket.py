from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TicketStatus = Literal["Open", "In Progress", "Resolved", "Closed"]

TicketCategory = Literal[
    "Royalty & Payments",
    "ISBN & Metadata Issues",
    "Printing & Quality",
    "Distribution & Availability",
    "Book Status & Production Updates",
    "General Inquiry",
]

TicketPriority = Literal["Critical", "High", "Medium", "Low"]


class BookSummary(BaseModel):
    id: str
    authorId: str
    title: str
    isbn: str
    genre: str
    publicationDate: str | None = None
    status: str
    mrp: float
    totalCopiesSold: int
    totalRoyaltyEarned: float
    royaltyPaid: float
    royaltyPending: float


class TicketCreateRequest(BaseModel):
    bookId: str | None = None
    subject: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=10, max_length=5000)


class TicketMessage(BaseModel):
    id: str
    ticketId: str
    senderRole: Literal["author", "admin"]
    senderId: str
    message: str
    isInternal: bool = False
    createdAt: datetime


class TicketInternalNote(BaseModel):
    id: str
    ticketId: str
    adminId: str
    note: str
    createdAt: datetime


class TicketSummary(BaseModel):
    id: str
    authorId: str
    bookId: str | None = None
    imageUrl: str | None = None
    subject: str
    description: str
    status: TicketStatus
    category: TicketCategory
    priority: TicketPriority

    # Admin assignment
    assigneeId: str | None = None

    # AI metadata
    aiMeta: dict = Field(default_factory=dict)

    createdAt: datetime
    updatedAt: datetime


class TicketDetail(TicketSummary):
    messages: list[TicketMessage] = Field(default_factory=list)

    internalNotes: list[TicketInternalNote] = Field(default_factory=list)


class AdminTicketUpdateRequest(BaseModel):
    status: TicketStatus | None = None
    category: TicketCategory | None = None
    priority: TicketPriority | None = None
    assigneeId: str | None = None


class AdminReplyRequest(BaseModel):
    message: str = Field(min_length=3, max_length=5000)


class AdminInternalNoteRequest(BaseModel):
    note: str = Field(min_length=3, max_length=5000)


class TicketListResponse(BaseModel):
    items: list[TicketSummary]
    total: int


class SSEEventPayload(BaseModel):
    ticketId: str
    eventType: str
    at: datetime