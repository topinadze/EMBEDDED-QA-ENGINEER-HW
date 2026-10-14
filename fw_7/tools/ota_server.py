#!/usr/bin/env python3
"""
Локальний OTA-сервер для SENTRY fw_7 (macOS / Linux / Windows, Python 3.8+, без залежностей).

Запуск:
    python3 ota_server.py --download      # один раз: скачати прошивки з GitHub у ./server_files
    python3 ota_server.py                 # запустити сервер на порту 8000

Потім на пристрої (після login):
    ota server http://<IP_КОМП'ЮТЕРА>:8000/fw7/
    ota check / ota update / ota update beta / ota install 2.1.0 force / ota broken
    ota server default                    # повернутись на GitHub

Режими для тестування помилок:
    --slow 20           віддавати прошивку зі швидкістю 20 KB/s (є час обірвати Wi-Fi)
    --drop-at 50        обірвати з'єднання на 50% прошивки
    --stable 2.3.0      що віддавати в stable.txt (за замовчуванням - як на GitHub)
    --beta 2.1.0        що віддавати в beta.txt

Спеціальні файли (для 'ota url http://<IP>:8000/test/<file>'):
    /test/garbage.bin      не прошивка (випадкові байти)
    /test/truncated.bin    обрізана наполовину прошивка
    /test/corrupted.bin    прошивка з пошкодженими байтами в середині
"""
import argparse
import http.server
import os
import random
import socket
import socketserver
import sys
import time
import urllib.request

GITHUB = "https://raw.githubusercontent.com/BohdanHorbanych/esp32-ota-files/main/fw7/"
BIN = "sentry_fw7.bin"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server_files")
FW = os.path.join(ROOT, "fw7")

args = None


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def download():
    os.makedirs(FW, exist_ok=True)
    stable = fetch(GITHUB + "stable.txt").decode().strip()
    beta = fetch(GITHUB + "beta.txt").decode().strip()
    print(f"GitHub: stable {stable}, beta {beta}")
    for name, data in (("stable.txt", stable), ("beta.txt", beta)):
        with open(os.path.join(FW, name), "w") as f:
            f.write(data + "\n")
    for sub in sorted({f"v{stable}", f"v{beta}", "broken"}):
        print(f"  {sub}/{BIN} ...", end=" ", flush=True)
        data = fetch(GITHUB + f"{sub}/{BIN}")
        os.makedirs(os.path.join(FW, sub), exist_ok=True)
        with open(os.path.join(FW, sub, BIN), "wb") as f:
            f.write(data)
        print(f"{len(data) // 1024} KB")
    print(f"Done: {FW}")


def ver_key(d):
    try:
        return tuple(int(x) for x in d[1:].split("."))
    except ValueError:
        return (-1,)


def any_firmware():
    # найновіша версія - щоб тестові файли не впирались у E408 (downgrade) на жодній прошивці
    dirs = [d for d in (os.listdir(FW) if os.path.isdir(FW) else [])
            if d.startswith("v") and os.path.isfile(os.path.join(FW, d, BIN))]
    if not dirs:
        return None
    with open(os.path.join(FW, max(dirs, key=ver_key), BIN), "rb") as f:
        return f.read()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *a):
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]} {fmt % a}")

    def send_bytes(self, data, ctype="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command == "HEAD":
            return
        is_fw = len(data) > 4096
        chunk = 4096
        sent = 0
        drop = int(len(data) * args.drop_at / 100) if (is_fw and args.drop_at) else None
        for i in range(0, len(data), chunk):
            part = data[i:i + chunk]
            if drop is not None and sent + len(part) > drop:
                print(f"    !!! dropping connection at {sent * 100 // len(data)}% (--drop-at)")
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            try:
                self.wfile.write(part)
            except (BrokenPipeError, ConnectionResetError):
                print(f"    client disconnected at {sent * 100 // len(data)}%")
                return
            sent += len(part)
            if is_fw and args.slow:
                time.sleep(len(part) / (args.slow * 1024))

    def route(self):
        path = self.path.split("?")[0]
        if path == "/fw7/stable.txt" and args.stable:
            return self.send_bytes((args.stable + "\n").encode(), "text/plain")
        if path == "/fw7/beta.txt" and args.beta:
            return self.send_bytes((args.beta + "\n").encode(), "text/plain")
        if path.startswith("/test/"):
            fw = any_firmware()
            name = path[6:]
            if name == "garbage.bin":
                return self.send_bytes(bytes(random.getrandbits(8) for _ in range(200 * 1024)))
            if fw and name == "truncated.bin":
                return self.send_bytes(fw[: len(fw) // 2])
            if fw and name == "corrupted.bin":
                b = bytearray(fw)
                for i in range(len(b) // 2, len(b) // 2 + 2048):
                    b[i] ^= 0xFF
                return self.send_bytes(bytes(b))
            return self.send_error(404)
        full = os.path.join(ROOT, path.lstrip("/"))
        if os.path.isfile(full):
            with open(full, "rb") as f:
                ctype = "text/plain" if full.endswith(".txt") else "application/octet-stream"
                return self.send_bytes(f.read(), ctype)
        return self.send_error(404)

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global args
    p = argparse.ArgumentParser(description="SENTRY fw_7 local OTA server")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--download", action="store_true", help="download firmware from GitHub and exit")
    p.add_argument("--slow", type=float, default=0, help="firmware speed limit, KB/s")
    p.add_argument("--drop-at", type=int, default=0, help="drop connection at N%% of firmware")
    p.add_argument("--stable", help="override stable.txt version")
    p.add_argument("--beta", help="override beta.txt version")
    args = p.parse_args()

    if args.download:
        download()
        return
    if not os.path.isdir(FW):
        print("No firmware yet. Run first:  python3 ota_server.py --download")
        sys.exit(1)

    ip = local_ip()
    print("SENTRY fw_7 local OTA server")
    print(f"  files:  {FW}")
    for d in sorted(os.listdir(FW)):
        print(f"          {d}")
    if args.slow:
        print(f"  mode:   slow {args.slow} KB/s")
    if args.drop_at:
        print(f"  mode:   drop connection at {args.drop_at}%")
    print("On the device (after login):")
    print(f"  ota server http://{ip}:{args.port}/fw7/")
    print(f"  ota url http://{ip}:{args.port}/test/garbage.bin")
    print("Stop: Ctrl+C. Back to GitHub on the device: ota server default")
    try:
        srv = Server(("0.0.0.0", args.port), Handler)
    except OSError as e:
        print(f"Cannot start on port {args.port}: {e.strerror}. Close the other server or use --port 8080")
        sys.exit(1)
    with srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
