# memory/long_term.py  —  Phase 2
from __future__ import annotations
import logging, os, uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class LongTermMemory:
    """
    ChromaDB vector store for persistent cross-session memory.
    Falls back gracefully if ChromaDB is not installed.
    """

    def __init__(self, persist_dir: str = "./ceo_memory_db"):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        self.available   = False
        self.vectorstore  = None
        self._init_chromadb()

    def _init_chromadb(self) -> None:
        try:
            from langchain_community.vectorstores import Chroma
            from langchain_community.embeddings import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={"device": "cpu"},
            )
            self.vectorstore = Chroma(
                collection_name="ceo_memory",
                embedding_function=embeddings,
                persist_directory=self.persist_dir,
            )
            self.available = True
            logger.info("LongTermMemory (ChromaDB) ready")
        except Exception as exc:
            logger.warning(f"ChromaDB unavailable — long-term memory disabled ({exc})")

    # ── Write ────────────────────────────────────
    def save(self, content: str, memory_type: str = "conversation") -> None:
        if not self.available: return
        try:
            doc_id = str(uuid.uuid4())
            self.vectorstore.add_texts(
                texts=[content],
                metadatas=[{"type": memory_type, "timestamp": datetime.now().isoformat(), "id": doc_id}],
                ids=[doc_id],
            )
            logger.debug(f"Saved [{memory_type}]: {content[:60]}...")
        except Exception as exc:
            logger.warning(f"Could not save to long-term memory: {exc}")

    def save_goal(self, goal: str)         -> None: self.save(f"USER GOAL: {goal}", "goal")
    def save_decision(self, decision: str) -> None: self.save(f"CEO DECISION: {decision}", "decision")
    def save_plan(self, plan: str)         -> None: self.save(f"STRATEGIC PLAN: {plan}", "plan")

    # ── Read ─────────────────────────────────────
    def recall(self, query: str, k: int = 4) -> str:
        if not self.available or not self.vectorstore: return ""
        try:
            docs = self.vectorstore.similarity_search(query, k=k)
            if not docs: return ""
            lines = []
            for i, doc in enumerate(docs, 1):
                ts    = doc.metadata.get("timestamp","")[:10]
                mtype = doc.metadata.get("type","memory")
                lines.append(f"[{i}] ({ts} | {mtype}): {doc.page_content}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning(f"Recall failed: {exc}")
            return ""

    # ── Utility ──────────────────────────────────
    def status(self) -> str:
        return "✅ ChromaDB active" if self.available else "⚠️  Disabled (ChromaDB not installed)"

    def __repr__(self) -> str:
        return f"LongTermMemory(persist_dir={self.persist_dir!r}, available={self.available})"