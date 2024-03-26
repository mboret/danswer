import json
import re

from sqlalchemy import create_engine
from sqlalchemy import text


class DanswerDB:
    def __init__(self, host: str, user: str, password: str) -> None:
        engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}")
        self._connection = engine.connect()

    def fetch_all(self, query: str) -> list:
        return [x._asdict() for x in self._connection.execute(text(query)).fetchall()]


class GenerateQueryHistoryAsLog:
    def __init__(self, danswer_db: DanswerDB) -> None:
        self.db = danswer_db

    def get_all_chat_feedback(self) -> list[dict]:
        return self.db.fetch_all("SELECT * FROM chat_feedback")

    def get_all_chat_message(self) -> list[dict]:
        return self.db.fetch_all("SELECT * FROM chat_message")

    def get_all_prompts(self) -> dict:
        return {x["id"]: x for x in self.db.fetch_all("SELECT * FROM prompt")}

    def grouped_messages(self) -> list[list]:
        grouped_message: list = []

        chat_messages = self.get_all_chat_message()

        messages_by_id = {x["id"]: x for x in chat_messages}
        user_messages = [x["id"] for x in chat_messages if x["message_type"] == "USER"]

        for user_msg_id in user_messages:
            messages = []
            system_msg_id = messages_by_id[user_msg_id]["parent_message"]
            assistant_msg_id = messages_by_id[user_msg_id]["latest_child_message"]

            if not (system_msg_id and assistant_msg_id):
                continue

            messages.append(messages_by_id[user_msg_id])
            messages.append(messages_by_id[system_msg_id])
            messages.append(messages_by_id[assistant_msg_id])

            if len(messages) != 3:
                print(f"ERROR. Missing something: {messages}")
                continue

            grouped_message.append(messages)

        return grouped_message

    def filter_messages(self, message: str) -> str:
        msg_to_filter = ["greetings", "it’s going to be a great day.", "welcome back!"]

        for msg in msg_to_filter:
            if re.search(msg, message.strip().lower()):
                return True

        return False

    def clean_message(self, message: str) -> str:
        if result := re.search(r"FINAL QUERY:(.*?)Hint", message.replace("\n", "")):
            message = result.group(1)

        return re.sub("<.*?>", "", message)

    def gather_logs(self):
        logs = []
        feedback = self.get_all_chat_feedback()
        prompts = self.get_all_prompts()

        for grp_messages in self.grouped_messages():
            qlog = {"feedback": None, "token_consumed": 0}

            for message in grp_messages:
                qlog["token_consumed"] += message["token_count"]

                if message["message_type"] == "USER":
                    qlog["user_query"] = self.clean_message(message["message"])

                    if self.filter_messages(qlog["user_query"]):
                        qlog["user_query"] = None
                        continue

                    qlog["date"] = message["time_sent"].isoformat()
                    qlog["prompt_name"] = prompts.get(
                        message["prompt_id"], {"name": "undefined"}
                    )["name"]
                elif message["message_type"] == "ASSISTANT":
                    qlog["llm_answer"] = message["message"]
                    f_data = [
                        x
                        for x in feedback
                        if x["chat_message_id"] == message["id"]
                        and x["is_positive"] != None
                    ]
                    if f_data:
                        qlog["feedback"] = f_data[0]["is_positive"]

            if "prompt_name" in qlog:
                logs.append(qlog)
            elif qlog.get("user_query"):
                print(f"Missing channel for the question: {qlog['user_query']}")

        return logs


def build_stats(logs):
    stats = {}

    with open("stats.json", "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=4)

    for log in logs:
        channel = log["prompt_name"]
        if channel not in stats:
            stats[channel] = {
                "positive": 0,
                "negative": 0,
                "not_evaluated": 0,
                "total": 0,
            }

        if log["feedback"]:
            stats[channel]["positive"] += 1
        elif log["feedback"] == False:
            stats[channel]["negative"] += 1
        else:
            stats[channel]["not_evaluated"] += 1

        stats[channel]["total"] += 1
    return stats


if __name__ == "__main__":
    db = DanswerDB("localhost", "postgres", "password")
    gquery = GenerateQueryHistoryAsLog(db)
    print(build_stats(gquery.gather_logs()))
