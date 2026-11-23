# ============================================================
# LUMINA AI - GÜVENLİ FIRESTORE GÖÇ ALTYAPISI
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional


class MigrationError(Exception):
    """Göç işlemi sırasında oluşan hata."""


class FirestoreMigrationTool:
    """Yerel JSON verisini Firestore'a güvenle taşımak için altyapı."""

    def __init__(self, store: Any, db: Any = None):
        self.store = store
        self.db = db

    # --------------------------------------------------------
    # Yardımcılar
    # --------------------------------------------------------
    def _load_source(self) -> Dict[str, Any]:
        try:
            data = self.store.load_all()
        except Exception as exc:
            raise MigrationError(f"Kaynak veri okunamadı: {exc}") from exc
        if not isinstance(data, dict):
            raise MigrationError("Kaynak veri geçerli bir JSON nesnesi değil.")
        return data

    def _profiles_collection(self):
        if self.db is None:
            raise MigrationError("Firestore istemcisi mevcut değil.")
        return self.db.collection("profiles")

    def _history_collection(self):
        if self.db is None:
            raise MigrationError("Firestore istemcisi mevcut değil.")
        return self.db.collection("chat_history")

    def _messages_collection(self, uid: str):
        return self._history_collection().document(uid).collection("messages")

    def _doc_exists(self, collection, doc_id: str) -> bool:
        try:
            snap = collection.document(doc_id).get()
            return bool(getattr(snap, "exists", False))
        except Exception:
            return False

    # --------------------------------------------------------
    # Audit
    # --------------------------------------------------------
    def audit(self) -> Dict[str, Any]:
        errors = []
        try:
            data = self._load_source()
        except MigrationError as exc:
            errors.append(str(exc))
            data = {}
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}

        histories = {k: v for k, v in data.items() if k != "profiles" and isinstance(v, list)}

        missing_uids = [uid for uid in histories if uid not in profiles]
        malformed_profiles = [uid for uid, p in profiles.items() if not isinstance(p, dict)]
        malformed_histories = [uid for uid, h in data.items() if uid != "profiles" and not isinstance(h, list)]
        total_messages = sum(len(h) for h in histories.values() if isinstance(h, list))

        return {
            "errors": errors,
            "profile_count": len(profiles),
            "history_count": len(histories),
            "total_messages": total_messages,
            "total_users": len(set(profiles) | set(histories)),
            "missing_profile_for_history": missing_uids,
            "malformed_profiles": malformed_profiles,
            "malformed_histories": malformed_histories,
        }

    # --------------------------------------------------------
    # Dry-run
    # --------------------------------------------------------
    def dry_run(self) -> Dict[str, Any]:
        data = self._load_source()
        profiles = data.get("profiles", {}) or {}
        histories = {k: v for k, v in data.items() if k != "profiles" and isinstance(v, list)}

        plan = {
            "profiles_to_create": [],
            "profiles_to_skip": [],
            "histories_to_create": [],
            "histories_to_skip": [],
            "messages_to_create": 0,
            "conflicts": [],
        }

        all_uids = set(profiles) | set(histories)
        for uid in all_uids:
            if uid in profiles:
                if self._doc_exists(self._profiles_collection(), uid):
                    plan["profiles_to_skip"].append(uid)
                    plan["conflicts"].append({"uid": uid, "type": "profile_exists"})
                else:
                    plan["profiles_to_create"].append(uid)

            if uid in histories:
                if self._doc_exists(self._history_collection(), uid):
                    plan["histories_to_skip"].append(uid)
                    plan["conflicts"].append({"uid": uid, "type": "history_exists"})
                else:
                    plan["histories_to_create"].append(uid)
                plan["messages_to_create"] += len(histories[uid])

        return plan

    # --------------------------------------------------------
    # Execute (guarded)
    # --------------------------------------------------------
    def execute(self, confirm: bool = False, backup_path: Optional[str] = None) -> Dict[str, Any]:
        if not confirm:
            raise MigrationError("Execute modu için confirm=True gerekli.")
        if self.db is None:
            raise MigrationError("Firestore istemcisi mevcut değil.")
        if not backup_path or not os.path.exists(backup_path):
            raise MigrationError("Doğrulanmış yedek dosyası bulunamadı.")

        data = self._load_source()
        profiles = data.get("profiles", {}) or {}
        histories = {k: v for k, v in data.items() if k != "profiles" and isinstance(v, list)}

        created_profiles = 0
        skipped_profiles = 0
        created_histories = 0
        skipped_histories = 0
        created_messages = 0
        skipped_messages = 0

        for uid, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            if self._doc_exists(self._profiles_collection(), uid):
                skipped_profiles += 1
            else:
                self._profiles_collection().document(uid).set(profile)
                created_profiles += 1

        for uid, history in histories.items():
            if not isinstance(history, list):
                continue
            if self._doc_exists(self._history_collection(), uid):
                skipped_histories += 1
                # Mesajları yine de eksikse tamamla
            else:
                self._history_collection().document(uid).set({"turn_count": len(history)})
                created_histories += 1

            msg_col = self._messages_collection(uid)
            for idx, turn in enumerate(history):
                msg_id = f"turn_{idx:06d}"
                if self._doc_exists(msg_col, msg_id):
                    skipped_messages += 1
                    continue
                msg_col.document(msg_id).set(turn if isinstance(turn, dict) else {"value": turn})
                created_messages += 1

        return {
            "created_profiles": created_profiles,
            "skipped_profiles": skipped_profiles,
            "created_histories": created_histories,
            "skipped_histories": skipped_histories,
            "created_messages": created_messages,
            "skipped_messages": skipped_messages,
        }

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------
    def verify(self) -> Dict[str, Any]:
        data = self._load_source()
        profiles = data.get("profiles", {}) or {}
        histories = {k: v for k, v in data.items() if k != "profiles" and isinstance(v, list)}

        dest_profiles = 0
        dest_histories = 0
        dest_messages = 0
        try:
            dest_profiles = len(list(self._profiles_collection().stream()))
            dest_histories = len(list(self._history_collection().stream()))
            for uid in histories:
                dest_messages += len(list(self._messages_collection(uid).stream()))
        except Exception:
            pass

        source_messages = sum(len(h) for h in histories.values() if isinstance(h, list))

        return {
            "source_profiles": len(profiles),
            "source_histories": len(histories),
            "source_messages": source_messages,
            "destination_profiles": dest_profiles,
            "destination_histories": dest_histories,
            "destination_messages": dest_messages,
            "profiles_match": len(profiles) <= dest_profiles,
            "histories_match": len(histories) <= dest_histories,
            "messages_match": source_messages <= dest_messages,
        }
