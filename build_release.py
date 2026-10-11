"""Build only allowlisted public files. Run separately on Windows and Linux."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ["rock_merchant_bot.py", "desktop_app.py", "tasks.ps1", "config.example.json",
                "README.md", "LICENSE", "VERSION", "requirements-build.txt", "build_release.py",
                "tests/test_merchant_bot.py", "tests/test_sharing.py", "release-notes.md",
                ".gitignore", ".github/workflows/rock-merchant-release.yml"]
RUNTIME_FILES = ["config.example.json", "README.md", "LICENSE", "VERSION"]


def zip_files(destination, pairs):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in pairs:
            archive.write(source, name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    version = (ROOT / "VERSION").read_text().strip()
    template = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    if template["qq"]["access_token"] or template["qq"]["target_ids"] or template["qq"]["target_id"]:
        raise RuntimeError("The public template must have empty credentials and targets.")
    for name in SOURCE_FILES:
        if not (ROOT / name).is_file():
            raise RuntimeError("Missing distribution file: " + name)
    windows = sys.platform == "win32"
    if not windows and (sys.platform != "linux" or platform.machine().lower() not in ("x86_64", "amd64")):
        raise RuntimeError("Build on Windows x64 or Linux x86_64.")
    binary_dir = out / "binary"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
               "--name", "RockMerchantQQ", "--distpath", str(binary_dir),
               "--workpath", str(out / "build"), "--specpath", str(out / "spec"),
               "--paths", str(ROOT)]
    if windows:
        command.append("--windowed")
    else:
        command.extend(["--exclude-module", "tkinter"])
    command.append(str(ROOT / "desktop_app.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    executable = binary_dir / ("RockMerchantQQ.exe" if windows else "RockMerchantQQ")
    for name in RUNTIME_FILES + (["tasks.ps1"] if windows else []):
        (binary_dir / name).write_bytes((ROOT / name).read_bytes())
    report = out / "self-test.json"
    subprocess.run([str(executable), "--self-test", "--self-test-output", str(report)],
                   cwd=binary_dir, check=True, timeout=60)
    if not json.loads(report.read_text())["config_readable"]:
        raise RuntimeError("Packaged application self-test failed.")
    target = "windows-x64" if windows else "linux-x86_64"
    prefix = f"RockMerchantQQ-v{version}"
    runtime = out / f"{prefix}-{target}.zip"
    pairs = [(executable, prefix + "/" + executable.name)]
    pairs.extend((binary_dir / name, prefix + "/" + name) for name in RUNTIME_FILES + (["tasks.ps1"] if windows else []))
    zip_files(runtime, pairs)
    source = out / f"{prefix}-source.zip"
    zip_files(source, [(ROOT / name, prefix + "-source/" + name) for name in SOURCE_FILES])
    for file in (runtime, source):
        with zipfile.ZipFile(file) as archive:
            if any(Path(name).name in ("config.json", "state.json", "merchant_bot.log") for name in archive.namelist()):
                raise RuntimeError("Personal runtime files must not be distributed.")
        print(file.name, file.stat().st_size, hashlib.sha256(file.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
