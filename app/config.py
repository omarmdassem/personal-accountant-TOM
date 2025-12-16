import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self) -> None:
        db = os.getenv("DATABASE_URL")
        if not db:
            raise RuntimeError("DATABASE_URL is missing. Create a .env file or export DATABASE_URL.")
        self.database_url = db
        self.sql_echo = os.getenv("SQL_ECHO", "0") == "1"

settings = Settings()
