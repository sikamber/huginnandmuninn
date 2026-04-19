from sqlmodel import SQLModel, create_engine

engine = create_engine("sqlite:///app.db")


def create_tables():
    SQLModel.metadata.create_all(engine)
