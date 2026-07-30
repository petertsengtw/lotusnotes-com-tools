"""診斷 portal 連線問題（含 requests 測試）"""
import ssl
import socket
import sys

HOST = "hltchnet.tzuchi.com.tw"
PORT = 1003

print(f"Python: {sys.version}")
print(f"OpenSSL: {ssl.OPENSSL_VERSION}")
print()

# 測試 1：純 TCP 連線
print("=== 測試 1: TCP 連線 ===")
try:
    sock = socket.create_connection((HOST, PORT), timeout=5)
    print("TCP OK")
    sock.close()
except Exception as e:
    print(f"TCP 失敗: {e}")
    sys.exit(1)

# 測試 2：SSL 握手（寬鬆設定）
print("\n=== 測試 2: SSL 握手 ===")
try:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("ALL:@SECLEVEL=0")
    with socket.create_connection((HOST, PORT), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as ssock:
            print(f"SSL OK  版本={ssock.version()}  cipher={ssock.cipher()}")
            # 測試 3：送出 HTTP GET
            print("\n=== 測試 3: HTTP GET ===")
            req = (
                f"GET /portal? HTTP/1.1\r\n"
                f"Host: {HOST}:{PORT}\r\n"
                f"Connection: close\r\n"
                f"User-Agent: Mozilla/5.0\r\n\r\n"
            )
            ssock.sendall(req.encode())
            resp = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                resp += chunk
            print(resp[:500].decode(errors="replace"))
except Exception as e:
    import traceback
    print(f"SSL/HTTP 失敗: {e}")
    traceback.print_exc()

# 測試 4：http.client 直接呼叫
print("\n=== 測試 4: http.client.HTTPSConnection ===")
import http.client
try:
    ctx4 = ssl.create_default_context()
    ctx4.check_hostname = False
    ctx4.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(HOST, PORT, context=ctx4, timeout=10)
    conn.request("GET", "/portal?", headers={"Host": f"{HOST}:{PORT}", "Connection": "close", "User-Agent": "Mozilla/5.0"})
    resp4 = conn.getresponse()
    print(f"http.client GET OK: {resp4.status}")
    conn.close()
except Exception as e:
    import traceback
    print(f"http.client GET 失敗: {e}")
    traceback.print_exc()

# 測試 5：requests + Connection:close + 無 Accept-Encoding
print("\n=== 測試 5: requests.get（Connection:close, 無壓縮）===")
import requests
import urllib3
urllib3.disable_warnings()
try:
    r = requests.get(
        f"https://{HOST}:{PORT}/portal?",
        verify=False,
        timeout=10,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Connection": "close",
            "Accept-Encoding": "identity",
        },
    )
    print(f"requests GET OK: {r.status_code}")
except Exception as e:
    import traceback
    print(f"requests GET 失敗: {e}")
    traceback.print_exc()
