"""
一次同步特約商店（Firestore）+ 福利公告（Ubuntu 網站伺服器）。
用法: venv32\\Scripts\\python.exe sync_all.py

store/sync_stores_to_firestore.py、bulletin/deploy_bulletin.py 兩支都是設計成
獨立執行的腳本（模組層級直接跑、用 from notes_store import ... 這種相對 import，
預期自己的目錄在 sys.path 上），所以這裡用 import 前先把兩個目錄各自加進
sys.path，再 import 進來讓它們的模組層級程式碼直接執行——不修改那兩支腳本本身。
只要其中一支用 raise SystemExit() 中止，就不會繼續跑下一支。
"""
import os
import sys

BASE_DIR = os.path.dirname(__file__)

sys.path.insert(0, os.path.join(BASE_DIR, "store"))
import sync_stores_to_firestore  # noqa: E402,F401

sys.path.insert(0, os.path.join(BASE_DIR, "bulletin"))
import deploy_bulletin  # noqa: E402,F401
