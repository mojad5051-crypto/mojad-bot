import sqlite3
from pathlib import Path
from typing import List, Tuple, Optional


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS infractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT DEFAULT 'Active',
                    appeal_status TEXT DEFAULT 'Appealable',
                    appeal_reason TEXT,
                    void_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    age TEXT NOT NULL,
                    experience TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    motivation TEXT NOT NULL,
                    status TEXT DEFAULT 'Pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roblox_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    roblox_username TEXT NOT NULL,
                    linked_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_infraction(self, user_id: int, moderator_id: int, reason: str, severity: str, appeal_status: str = "Appealable") -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO infractions (user_id, moderator_id, reason, severity, appeal_status) VALUES (?, ?, ?, ?, ?)",
                (user_id, moderator_id, reason, severity, appeal_status),
            )
        return cursor.lastrowid

    def add_application(self, user_id: int, user_name: str, age: str, experience: str, availability: str, motivation: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO applications (user_id, user_name, age, experience, availability, motivation) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, user_name, age, experience, availability, motivation),
            )
        return cursor.lastrowid

    def add_roblox_verification(self, user_id: int, roblox_username: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO roblox_verifications (user_id, roblox_username) VALUES (?, ?)",
                (user_id, roblox_username),
            )
        return cursor.lastrowid

    def get_infractions(self, user_id: int) -> List[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT * FROM infractions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return cursor.fetchall()

    def get_application(self, application_id: int) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        )
        return cursor.fetchone()

    def get_verification(self, user_id: int) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT * FROM roblox_verifications WHERE user_id = ? ORDER BY linked_at DESC LIMIT 1",
            (user_id,),
        )
        return cursor.fetchone()

    def get_infraction(self, infraction_id: int) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT * FROM infractions WHERE id = ?",
            (infraction_id,),
        )
        return cursor.fetchone()

    def update_infraction_status(self, infraction_id: int, status: str, appeal_reason: str = None, void_reason: str = None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE infractions SET status = ?, appeal_reason = ?, void_reason = ? WHERE id = ?",
                (status, appeal_reason, void_reason, infraction_id),
            )
