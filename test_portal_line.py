from auto_checkin import portal_login, send_line_message
from datetime import datetime

portal_login()
send_line_message(f"[測試] portal + LINE 通知 {datetime.now():%Y-%m-%d %H:%M:%S}")
