# this ensures that claude can not edit our db it only reads the data from db

import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

# Pre-seeded cloud database (used for recruiters and demo mode)
DEMO_DATABASE_URL = os.getenv("DATABASE_URL")

def get_readonly_connection(user_db_url: str = None):
    """
    Dual-mode connection resolver:
    1. Uses user_db_url if explicitly provided in the tool call.
    2. Falls back to DEMO_DATABASE_URL from .env if not provided.
    """
    target_url = user_db_url or DEMO_DATABASE_URL
    
    if not target_url:
        raise ValueError(
            "No database connection available. "
            "Please provide a PostgreSQL URL or set DATABASE_URL in .env."
        )

    conn = psycopg.connect(target_url, autocommit=False)
    with conn.cursor() as cur:
        # Enforce safety guardrails across both modes
        cur.execute("SET TRANSACTION READ ONLY;")
        cur.execute("SET statement_timeout = 5000;")
    return conn