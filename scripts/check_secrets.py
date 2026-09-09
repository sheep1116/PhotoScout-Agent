"""Check candidate repository files without printing any secret values."""
import subprocess
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / ".env")
secrets = [v.encode() for k,v in values.items() if k.endswith("KEY") and v and not v.startswith("your_")]
files = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],cwd=root).decode().split("\0")
leaks = []
for name in files:
    if not name or not (root/name).is_file():
        continue
    if name == ".env":
        leaks.append(name)
        continue
    content = (root/name).read_bytes()
    if any(value in content for value in secrets):
        leaks.append(name)
if leaks:
    print("Secret check failed. Affected files:", ", ".join(leaks))
    raise SystemExit(1)
ignored = subprocess.run(["git", "check-ignore", "-q", ".env"],cwd=root).returncode == 0
assert ignored, ".env must remain ignored"
print(f"Secret check passed: {len(files)-1} candidate files; .env ignored; no configured keys found.")
