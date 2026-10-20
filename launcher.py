"""Self-contained Windows launcher; all paths and state belong to this folder."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from getpass import getpass
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
STATE = ROOT / ".state"
PYTHON = ROOT / "runtime/python/python.exe"
PG = ROOT / "runtime/postgres/bin"
REDIS = ROOT / "runtime/redis/redis-server.exe"
INSTALL = STATE / "install.json"
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def environment():
    # Never inherit another installation's model credentials or configuration.
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOURNEYPILOT_")}
    for key in ("CONFIG_PATH", "VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "TAVILY_API_KEY",
                "BRAVE_API_KEY", "FIRECRAWL_API_KEY", "AMAP_MAPS_API_KEY", "BAIDU_MAP_API_KEY", "DUFFEL_API_KEY_LIVE"):
        env.pop(key, None)
    from dotenv import dotenv_values
    env.update({k: v for k, v in dotenv_values(APP / ".env").items() if v is not None})
    env.update({
        "CONFIG_PATH": str(APP / "config.yaml"),
        "HF_HOME": str(ROOT / "runtime/model-cache"),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "localhost,127.0.0.1,::1",
        "PATH": os.pathsep.join([str(ROOT / "runtime/node"), str(PG), str(PYTHON.parent), env.get("PATH", "")]),
    })
    return env


def load_install():
    return json.loads(INSTALL.read_text(encoding="utf-8")) if INSTALL.exists() else None


def save_install(data):
    STATE.mkdir(exist_ok=True)
    temp = INSTALL.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(INSTALL)


def free_port(preferred, used):
    for port in range(preferred, preferred + 100):
        if port in used:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                used.add(port)
                return port
            except OSError:
                pass
    raise RuntimeError("找不到可用的本机端口，请停止其他实例后重试。")


def initialize():
    import yaml
    STATE.mkdir(exist_ok=True)
    data = load_install()
    if data is None:
        used = set()
        data = {"database_port": free_port(58433, used), "redis_port": free_port(18379, used),
                "api_port": free_port(8011, used), "database_password": secrets.token_urlsafe(32),
                "redis_password": secrets.token_urlsafe(32)}
        save_install(data)
    target = APP / "config.yaml"
    if not target.exists():
        cfg = yaml.safe_load((APP / "config.portable.yaml").read_text(encoding="utf-8"))
        cfg["database"].update(port=data["database_port"], password=data["database_password"])
        cfg["redis"].update(port=data["redis_port"], password=data["redis_password"])
        cfg["server"]["port"] = data["api_port"]
        target.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def configure():
    from dotenv import dotenv_values, set_key
    initialize()
    path = APP / ".env"
    old = dotenv_values(path)
    print("\n默认使用 DeepSeek，也支持兼容 OpenAI 的接口。API Key 仅保存在本机 app/.env。")
    base = input(f"API 地址 [{old.get('JOURNEYPILOT_PRIMARY_MODEL__BASE_URL') or 'https://api.deepseek.com'}]: ").strip()
    primary = input(f"主模型 [{old.get('JOURNEYPILOT_PRIMARY_MODEL__MODEL_NAME') or 'deepseek-v4-pro'}]: ").strip()
    fast = input(f"快速模型 [{old.get('JOURNEYPILOT_FAST_MODEL__MODEL_NAME') or 'deepseek-v4-flash'}]: ").strip()
    key = getpass("API Key（输入不显示；已有密钥时回车保留）: ").strip()
    if not key and not old.get("JOURNEYPILOT_PRIMARY_MODEL__API_KEY"):
        raise RuntimeError("未填写 API Key。可以稍后重新运行 configure-api.cmd。")
    if key and any(c.isspace() for c in key):
        raise RuntimeError("API Key 不能包含空白字符。")
    values = {
        "JOURNEYPILOT_PRIMARY_MODEL__BASE_URL": base or old.get("JOURNEYPILOT_PRIMARY_MODEL__BASE_URL") or "https://api.deepseek.com",
        "JOURNEYPILOT_FAST_MODEL__BASE_URL": base or old.get("JOURNEYPILOT_PRIMARY_MODEL__BASE_URL") or "https://api.deepseek.com",
        "JOURNEYPILOT_PRIMARY_MODEL__MODEL_NAME": primary or old.get("JOURNEYPILOT_PRIMARY_MODEL__MODEL_NAME") or "deepseek-v4-pro",
        "JOURNEYPILOT_FAST_MODEL__MODEL_NAME": fast or old.get("JOURNEYPILOT_FAST_MODEL__MODEL_NAME") or "deepseek-v4-flash",
    }
    if key:
        values.update({f"JOURNEYPILOT_{tier}_MODEL__API_KEY": key for tier in ("PRIMARY", "FAST")})
    for name, value in values.items():
        set_key(str(path), name, value)
    print("配置已保存。运行 restart.cmd 应用新配置。")


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], cwd=kwargs.pop("cwd", APP), env=environment(),
                            creationflags=HIDDEN, **kwargs)
    if result.returncode:
        raise RuntimeError(f"命令失败（退出码 {result.returncode}）：{Path(str(args[0])).name}；请查看 .state 下的日志。")
    return result


def database_root(data):
    # PostgreSQL's Windows initdb cannot bootstrap in a non-ASCII install path.
    # A per-user SUBST alias keeps its internal SQL paths ASCII without moving files.
    if str(ROOT).isascii():
        return ROOT
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    def target(letter):
        output = ctypes.create_unicode_buffer(32768)
        return output.value if kernel.QueryDosDeviceW(letter, output, len(output)) else None
    expected = "\\??\\" + str(ROOT)
    previous = data.get("path_alias")
    if previous and target(previous) == expected:
        return Path(previous + "\\")
    for letter in reversed("DEFGHIJKLMNOPQRSTUVWXYZ"):
        drive = letter + ":"
        if target(drive) is None:
            run(["subst.exe", drive, ROOT], stdout=subprocess.DEVNULL)
            if target(drive) != expected:
                raise RuntimeError("无法建立数据库路径别名，请解压到纯英文路径（例如 D:\\JourneyPilot）。")
            data["path_alias"] = drive
            save_install(data)
            return Path(drive + "\\")
    raise RuntimeError("没有可用路径别名，请解压到纯英文路径（例如 D:\\JourneyPilot）。")


def process_identity(pid):
    """Check executable and creation time before stopping a recorded process."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return None
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return {"path": os.path.normcase(str(Path(buffer.value).resolve())), "created": created}
    finally:
        kernel.CloseHandle(handle)


def request(path, port, timeout=3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        return json.loads(response.read())


def wait_for(check, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("启动超时，请查看 .state 中的日志，或运行 status.cmd。")


def start(no_open=False, no_prompt=False):
    import psycopg
    import redis
    data = initialize()
    try:
        import onnxruntime  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 Microsoft Visual C++ x64 运行库，请从 https://aka.ms/vs/17/release/vc_redist.x64.exe 安装后重试；Python、Node、数据库无需安装。") from exc
    env = environment()
    if not env.get("JOURNEYPILOT_PRIMARY_MODEL__API_KEY"):
        if no_prompt:
            raise RuntimeError("请先运行 configure-api.cmd 填写自己的 API Key。")
        configure()
        env = environment()
    existing = data.get("api_pid")
    if existing and process_identity(existing) == data.get("api_identity"):
        wait_for(lambda: request("/api/config", data["api_port"]), 15)
        print(f"已运行：http://127.0.0.1:{data['api_port']}/?view=risk")
        if not no_open:
            webbrowser.open(f"http://127.0.0.1:{data['api_port']}/?view=risk")
        return
    pgroot = database_root(data)
    pgbin = pgroot / "runtime/postgres/bin"
    pgdata = pgroot / ".state/pgdata"
    if not (pgdata / "PG_VERSION").exists():
        password = pgroot / ".state/init-password.tmp"
        password.write_text(data["database_password"] + "\n", encoding="utf-8")
        try:
            print("首次启动：正在创建你的独立数据库……", flush=True)
            with (STATE / "initdb.log").open("w", encoding="utf-8") as log:
                run([pgbin / "initdb.exe", "-D", pgdata, "-U", "travel_agent", "--encoding=UTF8", "--locale=C",
                     "--auth-local=trust", "--auth-host=scram-sha-256", f"--pwfile={password}"], cwd=pgroot / "app", stdout=log, stderr=log)
        finally:
            password.unlink(missing_ok=True)
    status = subprocess.run([str(pgbin / "pg_ctl.exe"), "-D", str(pgdata), "status"],
                            creationflags=HIDDEN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if status.returncode:
        run([pgbin / "pg_ctl.exe", "-D", pgdata, "-l", pgroot / ".state/postgres.log", "-o",
             f"-h 127.0.0.1 -p {data['database_port']}", "-w", "start"], cwd=pgroot / "app")
    with psycopg.connect(host="127.0.0.1", port=data["database_port"], user="travel_agent",
                          password=data["database_password"], dbname="postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'travel_agent'").fetchone():
            conn.execute("CREATE DATABASE travel_agent OWNER travel_agent")
    client = redis.Redis(host="127.0.0.1", port=data["redis_port"], password=data["redis_password"], socket_timeout=2)
    try:
        client.ping()
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        # A dedicated store directory, not the historical ``.state/redis`` tree.
        # That tree can carry restrictive ACLs from an interrupted/sandboxed run;
        # Redis then fails its very first write with "Can't open the append-only
        # file ... Permission denied" and the whole launcher refuses to start.  A
        # fresh directory under the same state root has ordinary inherited
        # permissions and Redis owns every file in it.
        redis_dir = STATE / "redis-store"
        redis_dir.mkdir(exist_ok=True)
        with (STATE / "redis.log").open("ab") as log:
            proc = subprocess.Popen([str(REDIS), "--bind", "127.0.0.1", "--port", str(data["redis_port"]),
                                     "--requirepass", data["redis_password"], "--appendonly", "yes", "--dir", "."],
                                    cwd=redis_dir, env=env, stdout=log, stderr=log, creationflags=HIDDEN)
        data["redis_pid"] = proc.pid
        save_install(data)
        wait_for(client.ping, 30)
    print("正在检查数据库结构并启动应用……", flush=True)
    with (STATE / "migration.log").open("w", encoding="utf-8") as log:
        run([PYTHON, APP / "windows_entry.py", "journeypilot.py", "migrate"], stdout=log, stderr=log)
    with (STATE / "api.log").open("ab") as log:
        proc = subprocess.Popen([str(PYTHON), str(APP / "windows_entry.py"), "main.py"], cwd=APP,
                                env=env, stdout=log, stderr=log,
                                creationflags=HIDDEN | subprocess.CREATE_NEW_PROCESS_GROUP)
    data.update(api_pid=proc.pid, api_identity=process_identity(proc.pid))
    save_install(data)
    wait_for(lambda: request("/api/config", data["api_port"]), 120)
    health = request("/api/health/ready", data["api_port"], 15)
    print(f"启动成功：http://127.0.0.1:{data['api_port']}/?view=risk", flush=True)
    print("关闭本窗口后服务会继续运行；退出时双击 stop.cmd。")
    if not no_open:
        webbrowser.open(f"http://127.0.0.1:{data['api_port']}/?view=risk")


def stop():
    import redis
    data = load_install()
    if not data:
        print("尚未启动。")
        return
    pid = data.get("api_pid")
    if pid and data.get("api_identity") and process_identity(pid) == data["api_identity"]:
        if process_identity(pid)["path"] != os.path.normcase(str(PYTHON.resolve())):
            raise RuntimeError("进程不属于这个目录，停止操作已取消。")
        run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL)
    try:
        redis.Redis(host="127.0.0.1", port=data["redis_port"], password=data["redis_password"],
                    socket_timeout=3).shutdown(save=True)
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        pass
    pgroot = database_root(data)
    pgbin = pgroot / "runtime/postgres/bin"
    pgdata = pgroot / ".state/pgdata"
    status = subprocess.run([str(pgbin / "pg_ctl.exe"), "-D", str(pgdata), "status"],
                            creationflags=HIDDEN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not status.returncode:
        run([pgbin / "pg_ctl.exe", "-D", pgdata, "-m", "fast", "-w", "stop"], cwd=pgroot / "app")
    data.pop("api_pid", None)
    data.pop("api_identity", None)
    if data.get("path_alias"):
        alias = data.pop("path_alias")
        run(["subst.exe", alias, "/D"], stdout=subprocess.DEVNULL)
    save_install(data)
    print("已停止，配置和行程数据已保留。")


def status():
    data = load_install()
    if not data:
        print("尚未配置，请运行 start.cmd。")
        return
    result = request("/api/health/ready", data["api_port"], 15)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "restart", "configure", "status"], nargs="?", default="start")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-prompt", action="store_true")
    args = parser.parse_args()
    if args.action == "configure":
        configure()
    elif args.action == "stop":
        stop()
    elif args.action == "status":
        status()
    else:
        if args.action == "restart":
            stop()
        start(args.no_open, args.no_prompt)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\n启动/管理失败：{error}", file=sys.stderr)
        print("详情请查看本目录 .state 中的日志。", file=sys.stderr)
        raise SystemExit(1)
