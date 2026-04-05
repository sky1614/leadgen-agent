"""
Run this once to assign all existing data to a default client.
Usage: cd backend && python seed.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine
from app.models import Base, ClientDB, UserDB, LeadDB, CampaignDB, MessageLogDB, ConversationDB, ScrapedSourceDB, AgentJobDB, AgentJobItemDB

Base.metadata.create_all(bind=engine)
db = SessionLocal()

try:
    users = db.query(UserDB).all()
    for user in users:
        if not user.client_id:
            # Create a client for this user
            client = ClientDB(name=user.name or user.email, industry="other")
            db.add(client)
            db.flush()
            user.client_id = client.id
            user.role = "admin"

            # Assign all their data to this client
            db.query(LeadDB).filter(LeadDB.user_id == user.id).update({"client_id": client.id})
            db.query(CampaignDB).filter(CampaignDB.user_id == user.id).update({"client_id": client.id})
            db.query(MessageLogDB).filter(MessageLogDB.user_id == user.id).update({"client_id": client.id})
            db.query(AgentJobDB).filter(AgentJobDB.user_id == user.id).update({"client_id": client.id})
            print(f"Created client '{client.name}' for user {user.email}")

    db.commit()
    print("Seed complete.")
finally:
    db.close()
