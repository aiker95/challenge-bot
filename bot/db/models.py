from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    emoji = Column(String, nullable=False)
    completions = relationship("Completion", back_populates="user")

class Completion(Base):
    __tablename__ = 'completions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    date = Column(Date, nullable=False)
    completed = Column(Boolean, default=True)
    user = relationship("User", back_populates="completions") 