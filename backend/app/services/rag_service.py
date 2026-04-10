import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("rag_service")

# ── Constants ─────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = "./chroma_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MAX_RETRIEVED_EXAMPLES = 3
MIN_SIMILARITY_SCORE = 0.75
MIN_MESSAGES_FOR_RAG = 5

# ── Singletons ─────────────────────────────────────────────────────────────────
_chroma_client = None
_embedding_model = None
_singleton_lock = threading.Lock()


def get_chroma_client():
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    with _singleton_lock:
        if _chroma_client is not None:
            return _chroma_client
        try:
            import chromadb
            _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            return _chroma_client
        except Exception as e:
            logger.error(f"ChromaDB init failed: {e}")
            return None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _singleton_lock:
        if _embedding_model is not None:
            return _embedding_model
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
            return _embedding_model
        except Exception as e:
            logger.error(f"Embedding model load failed: {e}")
            return None


def get_or_create_collection(client_id: str, channel: str, language: str):
    try:
        client = get_chroma_client()
        if client is None:
            return None
        name = f"messages_{client_id}_{channel}_{language}"
        return client.get_or_create_collection(name=name)
    except Exception as e:
        logger.error(f"get_or_create_collection failed: {e}")
        return None


def store_successful_message(client_id: str, lead_id: str, message_text: str,
                              channel: str, language: str, industry: str,
                              reply_rate_signal: float, db):
    if reply_rate_signal < 0.5:
        return

    def _store():
        try:
            model = get_embedding_model()
            if model is None:
                return
            embedding = model.encode(message_text).tolist()
            collection = get_or_create_collection(client_id, channel, language)
            if collection is None:
                return
            doc_id = f"{client_id}_{lead_id}_{channel}"
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[message_text],
                metadatas=[{
                    "client_id": client_id,
                    "lead_id": lead_id,
                    "industry": industry,
                    "channel": channel,
                    "language": language,
                    "reply_rate_signal": float(reply_rate_signal),
                    "message_length": len(message_text),
                    "created_at": datetime.utcnow().isoformat(),
                }]
            )
        except Exception as e:
            logger.error(f"store_successful_message failed: {e}")

    threading.Thread(target=_store, daemon=True).start()


def retrieve_similar_messages(client_id: str, lead_profile: dict,
                               channel: str, language: str, industry: str,
                               n: int = 3) -> list:
    try:
        import signal as _signal

        role = lead_profile.get("role", "")
        ind = lead_profile.get("industry", industry or "")
        pain_points = lead_profile.get("pain_points", [])
        if isinstance(pain_points, list):
            pain_points = ", ".join(pain_points)
        query_str = f"{role} at {ind} company, pain points: {pain_points}"

        model = get_embedding_model()
        if model is None:
            return []

        collection = get_or_create_collection(client_id, channel, language)
        if collection is None:
            return []

        try:
            count = collection.count()
        except Exception:
            return []

        if count < MIN_MESSAGES_FOR_RAG:
            return []

        query_embedding = model.encode(query_str).tolist()

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                collection.query,
                query_embeddings=[query_embedding],
                n_results=min(n + 2, count),
                include=["documents", "metadatas", "distances"]
            )
            try:
                results = future.result(timeout=3)
            except concurrent.futures.TimeoutError:
                logger.warning("ChromaDB query timed out, falling back to static examples")
                return []

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        threshold = 1 - MIN_SIMILARITY_SCORE
        filtered = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            if dist <= threshold:
                filtered.append({
                    "message_text": doc,
                    "similarity": round(1 - dist, 4),
                    "reply_rate_signal": float(meta.get("reply_rate_signal", 0.0)),
                })

        filtered.sort(key=lambda x: x["reply_rate_signal"], reverse=True)
        return filtered[:MAX_RETRIEVED_EXAMPLES]

    except Exception as e:
        logger.error(f"retrieve_similar_messages failed: {e}")
        return []


def build_rag_few_shots(client_id: str, lead_profile: dict,
                        channel: str, language: str, industry: str) -> str:
    try:
        examples = retrieve_similar_messages(client_id, lead_profile, channel, language, industry)
        if not examples:
            return ""

        company = lead_profile.get("company", "this company")
        lines = [
            "Here are real messages that got replies from similar leads "
            "(use as style reference only, do NOT copy directly):\n"
        ]
        for i, ex in enumerate(examples, 1):
            lines.append(f"Example {i} (similarity: {ex['similarity']}):")
            lines.append(ex["message_text"])
            lines.append("")

        lines.append(f"Write a NEW original message inspired by these examples but personalized for {company}.")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"build_rag_few_shots failed: {e}")
        return ""


def index_historical_messages(client_id: str, db) -> dict:
    from ..models import MessageLogDB, LeadDB
    indexed = 0
    skipped = 0
    cutoff = datetime.utcnow() - timedelta(days=90)
    try:
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.status == "sent",
            MessageLogDB.sent_at >= cutoff,
        ).all()

        for log in logs:
            try:
                lead = db.query(LeadDB).filter(LeadDB.id == log.lead_id).first()
                if not lead or not log.message:
                    skipped += 1
                    continue

                if lead.status in ("replied", "meeting_booked"):
                    signal = 1.0
                elif lead.status == "contacted" and log.opened_at:
                    signal = 0.5
                else:
                    signal = 0.0

                if signal == 0.0:
                    skipped += 1
                    continue

                language = "en"
                try:
                    from ..models import ClientDB
                    client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
                    if client and isinstance(client.tone_config, dict):
                        language = client.tone_config.get("language", "en")
                except Exception:
                    pass

                store_successful_message(
                    client_id=client_id,
                    lead_id=log.lead_id,
                    message_text=log.message,
                    channel=log.channel or "email",
                    language=language,
                    industry=lead.industry or "",
                    reply_rate_signal=signal,
                    db=db,
                )
                indexed += 1
            except Exception as e:
                logger.error(f"index_historical: error on log {log.id}: {e}")
                skipped += 1

    except Exception as e:
        logger.error(f"index_historical_messages failed: {e}")

    return {"indexed": indexed, "skipped": skipped}


def sync_new_outcome(client_id: str, lead_id: str, outcome: str, db) -> None:
    signal_map = {"replied": 1.0, "opened": 0.5, "bounced": 0.0}
    signal = signal_map.get(outcome, 0.0)

    try:
        from ..models import MessageLogDB, LeadDB
        log = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.lead_id == lead_id,
        ).order_by(MessageLogDB.sent_at.desc()).first()

        if not log or not log.message:
            return

        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        industry = lead.industry if lead else ""

        language = "en"
        try:
            from ..models import ClientDB
            client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
            if client and isinstance(client.tone_config, dict):
                language = client.tone_config.get("language", "en")
        except Exception:
            pass

        store_successful_message(
            client_id=client_id,
            lead_id=lead_id,
            message_text=log.message,
            channel=log.channel or "email",
            language=language,
            industry=industry or "",
            reply_rate_signal=signal,
            db=db,
        )
    except Exception as e:
        logger.error(f"sync_new_outcome failed: {e}")
