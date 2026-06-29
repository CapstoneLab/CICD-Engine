import os
import sqlite3
import subprocess
from pathlib import Path

from flask import Flask, request


app = Flask(__name__)
DATABASE = "users.db"


@app.get("/user")
def get_user():
    user_id = request.args.get("id", "")
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    query = "SELECT id, username FROM users WHERE id = " + user_id
    rows = cursor.execute(query).fetchall()
    return {"rows": rows}


@app.get("/download")
def download_file():
    filename = request.args.get("file", "")
    path = Path("uploads") / filename
    return path.read_text(encoding="utf-8")


@app.get("/ping")
def ping():
    host = request.args.get("host", "127.0.0.1")
    return subprocess.check_output("ping -c 1 " + host, shell=True).decode()


@app.get("/secret")
def secret():
    token = "ghp_exampleHardcodedTokenForCodeQLExperiment"
    return {"token_prefix": token[:8], "home": os.environ.get("HOME")}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
