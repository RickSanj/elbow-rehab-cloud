import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from firebase_admin import auth, credentials, initialize_app
from elbow_rehab.service.logger import get_logger

logger = get_logger()

# 1. Initialize Firebase (Ensure this is called once)
# If running on Google Cloud, it uses default credentials automatically
try:
    initialize_app()
except ValueError:
    pass

socket_path = os.environ["INSTANCE_UNIX_SOCKET"]
db_user = os.environ["DB_USER"]
db_pass = os.environ["DB_PASS"]
db_name = os.environ["DB_NAME"]

DATABASE_URL = (
    f"postgresql+psycopg2://{db_user}:{db_pass}@/{db_name}?host={socket_path}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=2,
    pool_timeout=30,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def sync_firebase_users_to_db():
    # Create a new database session
    db = SessionLocal()

    try:
        # Fetch users from Firebase
        page = auth.list_users()
        while page:
            for user in page.users:
                logger.info(f"Syncing User: {user.email}")
                # Prepare the SQL Insert statement
                # We use "ON CONFLICT" to avoid errors if the user already exists
                query = text("""
                    INSERT INTO users (uid, email, role)
                    VALUES (:uid, :email, :role)
                    ON CONFLICT (uid) DO NOTHING
                """)

                # Execute the query using the session
                # Note: 'role' is required by your schema; we'll default to 'patient'
                db.execute(
                    query, {"uid": user.uid, "email": user.email, "role": "patient"}
                )

                logger.info(f"Synced User: {user.email}")

            page = page.get_next_page()

        # 3. Commit the transaction to save changes
        db.commit()
        logger.info("Synchronization complete.")

    except Exception as e:
        # Rollback if something goes wrong to keep data consistent
        db.rollback()
        logger.error(f"Error during sync: {e}")
    finally:
        # 4. Always close the session when finished
        db.close()
