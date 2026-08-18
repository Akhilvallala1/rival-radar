import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserTier(str, enum.Enum):
    starter = "starter"
    pro = "pro"
    team = "team"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    tier: Mapped[UserTier] = mapped_column(
        SAEnum(UserTier, name="user_tier"),
        default=UserTier.starter,
        nullable=False,
        server_default="starter",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    competitors: Mapped[list["Competitor"]] = relationship(back_populates="owner")
    alerts: Mapped[list["CompetitorAlert"]] = relationship(back_populates="owner")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    urls: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    slack_webhook: Mapped[str | None] = mapped_column(String(512))
    cadence: Mapped[str] = mapped_column(String(50), default="weekly")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User | None"] = relationship(back_populates="competitors")
    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["CompetitorAlert"]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_snapshot_comp_url_time", "competitor_id", "url", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    competitor: Mapped["Competitor"] = relationship(back_populates="snapshots")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    brief: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="running")

    competitor: Mapped["Competitor"] = relationship(back_populates="runs")


class CompetitorAlert(Base):
    __tablename__ = "competitor_alerts"
    __table_args__ = (
        UniqueConstraint("competitor_id", "user_id", "keyword", name="uq_alert_comp_user_kw"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    competitor: Mapped["Competitor"] = relationship(back_populates="alerts")
    owner: Mapped["User"] = relationship(back_populates="alerts")
