import json
import sqlite3
import os

app_data = os.getenv("LOCALAPPDATA")

app_dir = os.path.join(app_data, "slowAi")

os.makedirs(app_dir, exist_ok=True)

db_path = os.path.join(app_dir, "chat.db")

class ChatDB:

    def __init__(self, db_path=db_path):
        self.db_path = db_path

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=True
        )

        self.cursor = self.conn.cursor()

        # SQLite configuration
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

        self.initializeChatDb()

    # =========================================================
    # INITIALIZE DATABASE
    # =========================================================

    def initializeChatDb(self):

        table = self.conn.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'chats'
        """).fetchone()

        # Database does not exist yet
        if table is None:

            self._createChatsTable()

        else:

            table_sql = table[0] or ""
            table_sql_lower = table_sql.lower().replace(" ", "")

            # -------------------------------------------------
            # IMPORTANT
            #
            # Older versions of the application used:
            #
            # name TEXT UNIQUE
            #
            # or:
            #
            # UNIQUE(name)
            #
            # That prevents two chats from having the same name.
            #
            # We migrate that old database automatically.
            # -------------------------------------------------

            has_unique_name = (
                "unique(name)" in table_sql_lower
                or "nametextunique" in table_sql_lower
            )

            if has_unique_name:

                self._migrateOldChatsTable()

            else:

                columns = self.conn.execute(
                    "PRAGMA table_info(chats)"
                ).fetchall()

                column_names = [
                    column[1]
                    for column in columns
                ]

                required_columns = {
                    "id",
                    "name",
                    "messages"
                }

                if not required_columns.issubset(
                    set(column_names)
                ):

                    self._migrateOldChatsTable()

        self.conn.commit()

    # =========================================================
    # CREATE TABLE
    # =========================================================

    def _createChatsTable(self):

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                messages TEXT NOT NULL
            )
        """)

    # =========================================================
    # MIGRATE OLD TABLE
    # =========================================================

    def _migrateOldChatsTable(self):

        # Make sure we don't accidentally overwrite
        # another temporary table.
        old_table_exists = self.conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'chats_old'
        """).fetchone()

        if old_table_exists:

            self.conn.execute("""
                DROP TABLE chats_old
            """)

        # Rename old table
        self.conn.execute("""
            ALTER TABLE chats
            RENAME TO chats_old
        """)

        # Create new table without UNIQUE(name)
        self._createChatsTable()

        # Copy existing chats and preserve IDs
        self.conn.execute("""
            INSERT INTO chats (
                id,
                name,
                messages
            )
            SELECT
                id,
                name,
                messages
            FROM chats_old
        """)

        # Delete old table
        self.conn.execute("""
            DROP TABLE chats_old
        """)

    # =========================================================
    # CREATE CHAT
    # =========================================================

    def createChat(self, name, messages):

        """
        ALWAYS creates a new chat.

        The chat name is NOT an identifier.

        Example:

            createChat("What is Python?", [...])
            createChat("What is Python?", [...])

        creates:

            ID 1 -> What is Python?
            ID 2 -> What is Python?
        """

        self.cursor.execute("""
            INSERT INTO chats (
                name,
                messages
            )
            VALUES (?, ?)
        """, (
            name,
            json.dumps(
                messages,
                ensure_ascii=False
            )
        ))

        self.conn.commit()

        return self.cursor.lastrowid

    # =========================================================
    # UPDATE CHAT
    # =========================================================

    def updateChat(self, chat_id, messages):

        self.cursor.execute("""
            UPDATE chats
            SET messages = ?
            WHERE id = ?
        """, (
            json.dumps(
                messages,
                ensure_ascii=False
            ),
            chat_id
        ))

        self.conn.commit()

        return self.cursor.rowcount > 0

    # =========================================================
    # UPDATE CHAT NAME
    # =========================================================

    def updateChatName(self, chat_id, name):

        self.cursor.execute("""
            UPDATE chats
            SET name = ?
            WHERE id = ?
        """, (
            name,
            chat_id
        ))

        self.conn.commit()

        return self.cursor.rowcount > 0

    # =========================================================
    # GET ALL CHATS
    # =========================================================

    def getAllMessages(self):

        self.cursor.execute("""
            SELECT
                id,
                name,
                messages
            FROM chats
            ORDER BY id DESC
        """)

        rows = self.cursor.fetchall()

        result = []

        for chat_id, name, messages in rows:

            try:

                decoded_messages = json.loads(
                    messages
                )

                if not isinstance(
                    decoded_messages,
                    list
                ):
                    decoded_messages = []

            except (
                json.JSONDecodeError,
                TypeError
            ):

                decoded_messages = []

            result.append({
                "id": chat_id,
                "name": name,
                "messages": decoded_messages
            })

        return result

    # =========================================================
    # GET SINGLE CHAT
    # =========================================================

    def getChat(self, chat_id):

        self.cursor.execute("""
            SELECT
                id,
                name,
                messages
            FROM chats
            WHERE id = ?
        """, (
            chat_id,
        ))

        row = self.cursor.fetchone()

        if row is None:
            return None

        chat_id, name, messages = row

        try:

            decoded_messages = json.loads(
                messages
            )

            if not isinstance(
                decoded_messages,
                list
            ):
                decoded_messages = []

        except (
            json.JSONDecodeError,
            TypeError
        ):

            decoded_messages = []

        return {
            "id": chat_id,
            "name": name,
            "messages": decoded_messages
        }

    # =========================================================
    # BACKWARD COMPATIBILITY
    # =========================================================

    def getMessages(self, chat_id):

        return self.getChat(chat_id)

    # =========================================================
    # DELETE CHAT
    # =========================================================

    def deleteChat(self, chat_id):

        self.cursor.execute("""
            DELETE FROM chats
            WHERE id = ?
        """, (
            chat_id,
        ))

        self.conn.commit()

        return self.cursor.rowcount > 0

    # =========================================================
    # CHECK CHAT EXISTS
    # =========================================================

    def chatExists(self, chat_id):

        self.cursor.execute("""
            SELECT 1
            FROM chats
            WHERE id = ?
            LIMIT 1
        """, (
            chat_id,
        ))

        return self.cursor.fetchone() is not None

    # =========================================================
    # CLOSE
    # =========================================================

    def close(self):

        if self.conn is not None:

            self.conn.close()

            self.conn = None
            self.cursor = None