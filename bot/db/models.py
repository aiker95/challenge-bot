from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, ForeignKey, create_engine, BigInteger, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    name = Column(String)
    goal = Column(String)
    emoji = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    completions = relationship("Completion", back_populates="user", cascade="all, delete-orphan")

class Completion(Base):
    __tablename__ = "completions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    
    user = relationship("User", back_populates="completions")

# Создание асинхронного движка
def create_async_engine_from_url(url: str):
    return create_async_engine(url, echo=True)

# Создание асинхронной сессии
def create_async_session(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False) 