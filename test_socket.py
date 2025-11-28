import socket

HOST = "127.0.0.1"
PORT = 5050

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    s.bind((HOST, PORT))
    s.listen(1)
    print(f"Socket bind OK: {HOST}:{PORT}")
except Exception as e:
    print("Socket bind FAILED:", repr(e))
finally:
    s.close()
