import os
import sys
import shutil
import subprocess
import plistlib

APP_NAME = "Swan"
BUNDLE_ID = "com.axmadjon.swan"
SIGN_IDENTITY = "Developer ID Application: Axmadjon Yodgorov (WLT22AM64S)"
ENTITLEMENTS = "entitlements.plist"

def run(cmd, check=True):
    print(f"\n[EXEC] {cmd}")
    res = subprocess.run(cmd, shell=True)
    if check and res.returncode != 0:
        print(f"[FAIL] Command failed with exit code {res.returncode}: {cmd}")
        sys.exit(res.returncode)
    return res.returncode

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    build_dir = os.path.join(base_dir, "build")
    app_path = os.path.join(dist_dir, f"{APP_NAME}.app")
    dmg_path = os.path.join(dist_dir, f"{APP_NAME}.dmg")

    print(f"=== Starting Build Process for {APP_NAME} ===")

    # 1. Clean
    print("1. Cleaning old build artifacts...")
    for p in [build_dir, dist_dir]:
        if os.path.exists(p):
            shutil.rmtree(p)

    # 2. PyInstaller
    print("2. Running PyInstaller...")
    pyinstaller_cmd = (
        f"./.venv/bin/pyinstaller "
        f"--noconfirm --windowed "
        f"--name '{APP_NAME}' "
        f"--icon 'Swan.icns' "
        f"--osx-bundle-identifier '{BUNDLE_ID}' "
        f"--add-data 'sounds:sounds' "
        f"--add-data 'models/vosk-model-small-en-us-0.15:models/vosk-model-small-en-us-0.15' "
        f"--add-data 'hud_template.html:.' "
        f"--add-data 'settings_template.html:.' "
        f"--add-data 'swan_crystal_clean.png:.' "
        f"--add-data 'swan_logo_crystal.png:.' "
        f"--add-data 'swan_logo_transparent.png:.' "
        f"--collect-all 'vosk' "
        f"--add-binary '.venv/lib/python3.13/site-packages/vosk/libvosk.dyld:vosk' "
        f"--hidden-import 'Cocoa' "
        f"--hidden-import 'PyObjCTools' "
        f"--hidden-import 'WebKit' "
        f"--hidden-import 'Quartz' "
        f"--hidden-import 'sounddevice' "
        f"--hidden-import 'vosk' "
        f"--hidden-import 'google.genai' "
        f"--hidden-import 'websockets' "
        f"--hidden-import 'PIL' "
        f"--hidden-import 'pynput' "
        f"--hidden-import 'resource_helper' "
        f"app.py"
    )
    run(pyinstaller_cmd)

    if not os.path.exists(app_path):
        print(f"[ERROR] {app_path} does not exist after PyInstaller.")
        sys.exit(1)

    # Ensure libvosk.dyld is inside Contents/Frameworks/vosk
    frameworks_vosk = os.path.join(app_path, "Contents", "Frameworks", "vosk")
    os.makedirs(frameworks_vosk, exist_ok=True)
    vosk_src = os.path.join(base_dir, ".venv/lib/python3.13/site-packages/vosk/libvosk.dyld")
    vosk_dst = os.path.join(frameworks_vosk, "libvosk.dyld")
    if os.path.exists(vosk_src):
        shutil.copy2(vosk_src, vosk_dst)
        run(f"codesign --force --sign '{SIGN_IDENTITY}' '{vosk_dst}'")

    # 3. Enhance Info.plist
    print("3. Updating Info.plist with macOS permissions...")
    plist_path = os.path.join(app_path, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        pl = plistlib.load(f)

    pl["CFBundleDisplayName"] = APP_NAME
    pl["CFBundleIdentifier"] = BUNDLE_ID
    pl["CFBundleShortVersionString"] = "1.0.0"
    pl["CFBundleVersion"] = "1.0.0"
    pl["NSMicrophoneUsageDescription"] = "Swan microfoningiz orqali buyruqlarni real vaqtda eshitadi va bajaradi."
    pl["NSSpeechRecognitionUsageDescription"] = "Swan 'Hey Swan' uyg'onish so'zini aniqlash uchun nutqni tahlil qiladi."
    pl["NSAppleEventsUsageDescription"] = "Swan tizim buyruqlarini va ilovalarni boshqarish uchun ruxsat talab qiladi."
    pl["LSUIElement"] = False  # Allows standard application activation with dock/menubar support

    with open(plist_path, "wb") as f:
        plistlib.dump(pl, f)

    # 4. Deep code signing with Hardened Runtime
    print("4. Code signing Swan.app with Hardened Runtime...")
    sign_cmd = (
        f"codesign --force --deep --strict --options runtime "
        f"--entitlements '{ENTITLEMENTS}' "
        f"--sign '{SIGN_IDENTITY}' "
        f"'{app_path}'"
    )
    run(sign_cmd)

    # Verify signature
    print("5. Verifying code signature...")
    run(f"codesign -vvv --deep --strict '{app_path}'")

    # 6. Create DMG
    print("6. Creating DMG installer with create-dmg...")
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    create_dmg_cmd = (
        f"/opt/homebrew/bin/create-dmg "
        f"--volname 'Swan AI Assistant' "
        f"--volicon 'Swan.icns' "
        f"--window-pos 200 120 "
        f"--window-size 660 400 "
        f"--icon-size 128 "
        f"--icon 'Swan.app' 180 170 "
        f"--hide-extension 'Swan.app' "
        f"--app-drop-link 480 170 "
        f"'{dmg_path}' "
        f"'{app_path}'"
    )
    run(create_dmg_cmd)

    # 7. Sign DMG
    print("7. Signing DMG with Developer ID...")
    run(f"codesign --force --sign '{SIGN_IDENTITY}' '{dmg_path}'")
    run(f"codesign -vvv --strict '{dmg_path}'")

    print(f"\n[SUCCESS] Swan.app and {dmg_path} successfully built and signed!")

if __name__ == "__main__":
    main()
