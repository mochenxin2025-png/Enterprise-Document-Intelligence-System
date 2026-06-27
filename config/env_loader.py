"""
加载 Hermes 的环境变量到 os.environ。
EDIS 项目不存储自己的 .env，而是从 Hermes 的 .env 读取。
"""
import os

def load_hermes_env():
    hermes_env = os.path.expandvars(r"%LOCALAPPDATA%\hermes\.env")
    if not os.path.exists(hermes_env):
        print(f"[EDIS] WARNING: Hermes .env not found at {hermes_env}")
        return
    
    loaded = 0
    with open(hermes_env, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val and key not in os.environ:
                os.environ[key] = val
                loaded += 1
    
    print(f"[EDIS] Loaded {loaded} env vars from Hermes")

# Auto-load on import
load_hermes_env()
