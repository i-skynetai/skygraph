from sqlalchemy import Column, ForeignKey, Integer, String
from db import Base


class Org(Base):
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)
    org_id = Column(Integer, ForeignKey("orgs.id"))
