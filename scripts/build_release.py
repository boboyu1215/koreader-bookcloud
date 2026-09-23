"""Build an installable plugin ZIP using only an explicit file allowlist."""
from pathlib import Path
import hashlib
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text().strip()
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", version):
    raise SystemExit("Invalid version")
meta = (ROOT / "plugin/bookcloud.koplugin/_meta.lua").read_text()
if f'version = "{version}"' not in meta:
    raise SystemExit("Plugin version does not match VERSION")
if f"'version':'{version}'" not in (ROOT / "server/app.py").read_text():
    raise SystemExit("Server version does not match VERSION")
if f"BookCloud {version}" not in (ROOT / "server/admin.html").read_text():
    raise SystemExit("Admin version does not match VERSION")
out = ROOT / "dist"
out.mkdir(exist_ok=True)
archive = out / f"bookcloud.koplugin-{version}.zip"
files = {
    "bookcloud.koplugin/main.lua": ROOT / "plugin/bookcloud.koplugin/main.lua",
    "bookcloud.koplugin/bookcloudmenu.lua": ROOT / "plugin/bookcloud.koplugin/bookcloudmenu.lua",
    "bookcloud.koplugin/_meta.lua": ROOT / "plugin/bookcloud.koplugin/_meta.lua",
    "bookcloud.koplugin/LICENSE": ROOT / "LICENSE",
    "bookcloud.koplugin/THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
}
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for name, path in files.items():
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, path.read_bytes())
with zipfile.ZipFile(archive) as z:
    if z.testzip() is not None or set(z.namelist()) != set(files):
        raise SystemExit("Archive validation failed")
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(out / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
print(f"Built {archive.name} ({archive.stat().st_size:,} bytes)")
print(f"SHA-256: {digest}")
