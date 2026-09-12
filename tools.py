import subprocess
import os
import asyncio
import re
import shutil
import glob
import urllib.parse
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from google.genai import types

# Callback to notify app of mode changes
mode_change_callback: Optional[Callable[[str], None]] = None

# Callback to notify app of dismissal
dismiss_callback: Optional[Callable[[], None]] = None

def set_dismiss_callback(cb: Callable[[], None]):
    global dismiss_callback
    dismiss_callback = cb

def dismiss_assistant(reason: Optional[str] = None) -> Dict[str, Any]:
    """Dismisses and hides the assistant from the screen immediately."""
    global dismiss_callback
    if dismiss_callback:
        dismiss_callback()
    return {"status": "success", "message": "Assistant dismissed and hidden."}

def remember_user_fact(fact: str, category: Optional[str] = "preference") -> Dict[str, Any]:
    """Stores a fact or preference about the user into Swan's long-term memory."""
    try:
        from memory_manager import memory_manager
        success = memory_manager.add_fact(fact, category)
        if success:
            return {"status": "success", "message": f"Fakt xotiraga saqlandi: '{fact}'"}
        else:
            return {"status": "success", "message": f"Fakt allaqachon xotirada mavjud: '{fact}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_user_memory() -> Dict[str, Any]:
    """Retrieves what Swan currently remembers about the user."""
    try:
        from memory_manager import memory_manager
        return {
            "status": "success",
            "owner": memory_manager.get_owner_info(),
            "preferences": memory_manager.get_preferences(),
            "learned_facts": memory_manager.get_learned_facts()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

APP_SEARCH_DIRS = [
    "/Applications",
    "/System/Applications",
    "/System/Applications/Utilities",
    os.path.expanduser("~/Applications"),
    os.path.expanduser("~/Applications/Chrome Apps.localized"),
    os.path.expanduser("~/Applications/Chromium Apps.localized")
]

APP_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "terminal": "Terminal",
    "finder": "Finder",
    "notes": "Notes",
    "calculator": "Calculator",
    "calendar": "Calendar",
    "music": "Music",
    "spotify": "Spotify",
    "mail": "Mail",
    "messages": "Messages",
    "settings": "System Settings",
    "system settings": "System Settings",
    "photos": "Photos",
    "reminders": "Reminders",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "youtube": "YouTube",
    "chatgpt": "ChatGPT",
    "chat gpt": "ChatGPT",
    "gemini": "Google Gemini",
    "google gemini": "Google Gemini",
    "elevenlabs": "ElevenLabs",
    "eleven labs": "ElevenLabs",
    "claude": "Claude",
    "github": "GitHub",
    "vercel": "Vercel",
    "supabase": "Supabase Studio",
    "supabase studio": "Supabase Studio",
    "ai studio": "Google AI Studio",
    "google ai studio": "Google AI Studio",
    "notebooklm": "NotebookLM",
    "notebook": "NotebookLM",
    "twitter": "X",
    "x": "X",
    "resend": "Emails · Resend",
    "al-xorazmiy": "Al-Xorazmiy",
    "xorazmiy": "Al-Xorazmiy",
    "perplexity": "Perplexity Computer"
}

def set_mode_callback(cb: Callable[[str], None]):
    global mode_change_callback
    mode_change_callback = cb

def find_installed_app(query: str) -> Optional[str]:
    """Scans macOS app directories including web apps (Chrome Apps / PWAs)."""
    q = query.strip().lower()
    target = APP_ALIASES.get(q, q).lower()

    # 1. Exact base name match
    for d in APP_SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            for item in os.listdir(d):
                if item.endswith(".app"):
                    base = item[:-4].lower()
                    if base == target or base == q:
                        return os.path.join(d, item)
        except Exception:
            pass

    # 2. Substring match
    for d in APP_SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            for item in os.listdir(d):
                if item.endswith(".app"):
                    base = item[:-4].lower()
                    if target in base or base in target:
                        return os.path.join(d, item)
                    if q in base:
                        return os.path.join(d, item)
        except Exception:
            pass

    return None

def open_app(app_name: str) -> Dict[str, Any]:
    """Opens a macOS application or downloaded web app."""
    clean_name = app_name.strip()
    
    # 1. Try finding full path in app directories (including Chrome/Web apps)
    app_path = find_installed_app(clean_name)
    if app_path:
        try:
            res = subprocess.run(["open", app_path], capture_output=True, text=True)
            if res.returncode == 0:
                app_title = os.path.basename(app_path)[:-4]
                return {"status": "success", "message": f"Successfully launched {app_title}", "path": app_path}
        except Exception:
            pass

    # 2. Fallback to open -a with alias or clean name
    target_app = APP_ALIASES.get(clean_name.lower(), clean_name)
    try:
        res = subprocess.run(["open", "-a", target_app], capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "success", "message": f"Successfully launched {target_app}"}
        
        # 3. Fallback: try raw name
        res2 = subprocess.run(["open", "-a", clean_name], capture_output=True, text=True)
        if res2.returncode == 0:
            return {"status": "success", "message": f"Successfully launched {clean_name}"}
            
        return {"status": "error", "message": res.stderr.strip() or f"Could not find application {app_name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def close_app(app_name: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Quits or closes a macOS application or the active window/application."""
    clean_name = (app_name or "").strip()

    # Case 1: Close active / frontmost window or application
    if not clean_name or clean_name.lower() in [
        "this", "current", "front", "frontmost", "active", "this window", "this app", "window", "active window"
    ]:
        try:
            scpt = 'tell application "System Events" to get name of first process whose frontmost is true'
            res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
            front_app = res.stdout.strip()
            if front_app:
                if "window" in clean_name.lower():
                    scpt_win = f'tell application "System Events" to tell process "{front_app}" to click (first button whose subrole is "AXCloseButton") of (first window)'
                    res_win = subprocess.run(["osascript", "-e", scpt_win], capture_output=True, text=True)
                    if res_win.returncode == 0:
                        return {"status": "success", "message": f"Closed window in {front_app}"}
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "w" using command down'])
                    return {"status": "success", "message": f"Closed active window in {front_app}"}
                else:
                    subprocess.run(["osascript", "-e", f'tell application "{front_app}" to quit'])
                    return {"status": "success", "message": f"Closed {front_app}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Case 2: Specific application requested
    target_app = APP_ALIASES.get(clean_name.lower(), clean_name)

    # 2a. Query all currently running GUI apps
    running_apps = []
    try:
        scpt = 'tell application "System Events" to get name of every process whose background only is false'
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            running_apps = [p.strip() for p in res.stdout.split(",") if p.strip()]
    except Exception:
        pass

    # 2b. Match target against running apps
    matched_app = None
    target_lower = target_app.lower()
    clean_lower = clean_name.lower()

    for app in running_apps:
        app_lower = app.lower()
        if app_lower == target_lower or app_lower == clean_lower:
            matched_app = app
            break

    if not matched_app:
        for app in running_apps:
            app_lower = app.lower()
            if target_lower in app_lower or app_lower in target_lower or clean_lower in app_lower:
                matched_app = app
                break

    app_to_quit = matched_app or target_app

    # 2c. Try graceful AppleScript quit
    try:
        scpt = f'tell application "{app_to_quit}" to quit'
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "success", "message": f"Successfully closed {app_to_quit}"}
    except Exception:
        pass

    # 2d. If AppleScript failed, try System Events quit
    try:
        scpt2 = f'''
        tell application "System Events"
            set matchingProcs to (every process whose name is "{app_to_quit}")
            repeat with p in matchingProcs
                tell p to quit
            end repeat
        end tell
        '''
        res2 = subprocess.run(["osascript", "-e", scpt2], capture_output=True, text=True)
        if res2.returncode == 0:
            return {"status": "success", "message": f"Closed {app_to_quit}"}
    except Exception:
        pass

    # 2e. Force kill if requested
    if force:
        try:
            subprocess.run(["pkill", "-i", "-f", app_to_quit])
            return {"status": "success", "message": f"Force closed {app_to_quit}"}
        except Exception:
            pass

    return {"status": "error", "message": f"Could not find or close {app_name}. It may not be running."}

COMMON_DIRECTORIES = {
    "desktop": os.path.expanduser("~/Desktop"),
    "downloads": os.path.expanduser("~/Downloads"),
    "download": os.path.expanduser("~/Downloads"),
    "documents": os.path.expanduser("~/Documents"),
    "document": os.path.expanduser("~/Documents"),
    "pictures": os.path.expanduser("~/Pictures"),
    "photos": os.path.expanduser("~/Pictures"),
    "movies": os.path.expanduser("~/Movies"),
    "videos": os.path.expanduser("~/Movies"),
    "music": os.path.expanduser("~/Music"),
    "home": os.path.expanduser("~"),
    "library": os.path.expanduser("~/Library"),
    "applications": "/Applications"
}

def clean_folder_name(name: str) -> str:
    """Cleans up spoken folder names like 'my downloads folder', 'the desktop'."""
    s = name.strip()
    s = re.sub(r'^(my|the|our)\s+', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(folder|directory|dir)$', '', s, flags=re.IGNORECASE)
    return s.strip()

def resolve_path(path_str: str, default_parent: Optional[str] = None) -> str:
    """Resolves a user-provided or spoken path into an absolute filesystem path."""
    clean = clean_folder_name(path_str).strip().strip("'\"")
    lower = clean.lower()

    # 1. Expand user ~/path or absolute /path
    if clean.startswith("~") or clean.startswith("/"):
        return os.path.expanduser(clean)

    # 2. Check known common directory names
    if lower in COMMON_DIRECTORIES:
        return COMMON_DIRECTORIES[lower]

    # 3. Check if path starts with a known directory (e.g. "Desktop/New Folder for Text", "downloads/sub")
    parts = clean.split("/")
    first_part = parts[0].strip().lower()
    if first_part in COMMON_DIRECTORIES:
        rest = "/".join(parts[1:])
        return os.path.join(COMMON_DIRECTORIES[first_part], rest)

    # 4. Check relative to user home directory
    home_candidate = os.path.join(os.path.expanduser("~"), clean)
    if os.path.exists(home_candidate):
        return home_candidate

    # 5. If a default parent is specified (e.g. Desktop)
    if default_parent:
        parent_resolved = resolve_path(default_parent)
        comb = os.path.join(parent_resolved, clean)
        if os.path.exists(comb):
            return comb

    # 6. Search common user directories if only a bare folder or subfolder name is given
    for search_dir in [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~")
    ]:
        candidate = os.path.join(search_dir, clean)
        if os.path.exists(candidate):
            return candidate

    # 7. Fallback with default_parent
    if default_parent:
        return os.path.join(resolve_path(default_parent), clean)

    # 8. Check if home_candidate parent exists
    if os.path.exists(os.path.dirname(home_candidate)):
        return home_candidate

    # 9. Default fallback to Desktop
    return os.path.join(os.path.expanduser("~/Desktop"), clean)

CATEGORY_EXTENSIONS = {
    "images": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "image": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "photos": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "photo": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "pictures": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "picture": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.tiff", "*.svg"],
    "videos": ["*.mp4", "*.mov", "*.m4v", "*.mkv", "*.avi", "*.webm"],
    "video": ["*.mp4", "*.mov", "*.m4v", "*.mkv", "*.avi", "*.webm"],
    "movies": ["*.mp4", "*.mov", "*.m4v", "*.mkv", "*.avi", "*.webm"],
    "movie": ["*.mp4", "*.mov", "*.m4v", "*.mkv", "*.avi", "*.webm"],
    "documents": ["*.pdf", "*.docx", "*.doc", "*.txt", "*.xlsx", "*.xls", "*.pptx", "*.ppt", "*.csv", "*.md"],
    "document": ["*.pdf", "*.docx", "*.doc", "*.txt", "*.xlsx", "*.xls", "*.pptx", "*.ppt", "*.csv", "*.md"],
    "docs": ["*.pdf", "*.docx", "*.doc", "*.txt", "*.xlsx", "*.xls", "*.pptx", "*.ppt", "*.csv", "*.md"],
    "audio": ["*.mp3", "*.wav", "*.m4a", "*.flac", "*.aac", "*.aiff", "*.ogg"],
    "music": ["*.mp3", "*.wav", "*.m4a", "*.flac", "*.aac", "*.aiff", "*.ogg"],
    "songs": ["*.mp3", "*.wav", "*.m4a", "*.flac", "*.aac", "*.aiff", "*.ogg"],
    "archives": ["*.zip", "*.tar.gz", "*.tgz", "*.rar", "*.7z", "*.gz"],
    "zips": ["*.zip", "*.tar.gz", "*.tgz", "*.rar", "*.7z", "*.gz"],
    "pdfs": ["*.pdf"],
    "pdf": ["*.pdf"],
    "screenshots": ["Screenshot*.*", "Screen Shot*.*", "screenshot*.*"],
    "screenshot": ["Screenshot*.*", "Screen Shot*.*", "screenshot*.*"],
}

def normalize_filename(name: str) -> str:
    """Normalizes a filename for fuzzy spoken matching (lowercased, spaces/underscores/hyphens equated, articles stripped)."""
    s = name.strip().lower()
    # Replace separators with a single space FIRST
    s = re.sub(r'[\s_\-]+', ' ', s)
    # Remove leading articles: the, a, an, my
    s = re.sub(r'^(the|a|an|my)\s+', '', s)
    return s.strip()

def find_item_fuzzy(query: str, search_dirs: List[str], max_sub_depth: int = 2) -> Optional[str]:
    """Finds a file or directory matching query across search_dirs using exact, normalized, stem, and subfolder matching."""
    q_clean = query.strip().strip("'\"")
    if not q_clean:
        return None

    # 1. Direct path check
    if os.path.exists(q_clean):
        return os.path.abspath(q_clean)

    expanded = os.path.expanduser(q_clean)
    if os.path.exists(expanded):
        return os.path.abspath(expanded)

    q_norm = normalize_filename(q_clean)
    q_stem_norm = normalize_filename(os.path.splitext(q_clean)[0])

    SKIP_DIRS = {".git", ".venv", "node_modules", "Library", ".Trash", "cache", "__pycache__"}

    # Pass 1: Direct children exact & normalized match
    for root_dir in search_dirs:
        if not os.path.exists(root_dir):
            continue
        try:
            with os.scandir(root_dir) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.name == q_clean or entry.name.lower() == q_clean.lower():
                        return entry.path
                    e_norm = normalize_filename(entry.name)
                    if e_norm == q_norm:
                        return entry.path
                    e_stem_norm = normalize_filename(os.path.splitext(entry.name)[0])
                    if e_stem_norm == q_norm or e_stem_norm == q_stem_norm:
                        return entry.path
                    # Substring matching (e.g. 'choice trap' in 'the choice trap')
                    if len(q_norm) >= 4 and (q_norm in e_norm or q_stem_norm in e_stem_norm or e_stem_norm in q_stem_norm):
                        return entry.path
        except (PermissionError, OSError):
            continue

    # Pass 2: Search subdirectories up to max_sub_depth
    for root_dir in search_dirs:
        if not os.path.exists(root_dir):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root_dir):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
                rel_depth = os.path.relpath(dirpath, root_dir).count(os.sep)
                if rel_depth > max_sub_depth:
                    continue

                for fname in filenames + dirnames:
                    if fname.startswith("."):
                        continue
                    full_path = os.path.join(dirpath, fname)
                    if fname.lower() == q_clean.lower():
                        return full_path
                    f_norm = normalize_filename(fname)
                    if f_norm == q_norm:
                        return full_path
                    f_stem_norm = normalize_filename(os.path.splitext(fname)[0])
                    if f_stem_norm == q_norm or f_stem_norm == q_stem_norm:
                        return full_path
                    if len(q_norm) >= 4 and (q_norm in f_norm or q_stem_norm in f_stem_norm or f_stem_norm in q_stem_norm):
                        return full_path
        except (PermissionError, OSError):
            continue

    return None

def open_folder(folder_path: str) -> Dict[str, Any]:
    """Opens a folder or directory in macOS Finder."""
    resolved = resolve_path(folder_path)
    if not os.path.exists(resolved):
        matched = find_item_fuzzy(folder_path, [
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~")
        ])
        if matched and os.path.isdir(matched):
            resolved = matched
        elif not os.path.exists(resolved):
            return {"status": "error", "message": f"Folder '{folder_path}' does not exist."}

    try:
        res = subprocess.run(["open", resolved], capture_output=True, text=True)
        if res.returncode == 0:
            folder_name = os.path.basename(resolved) or resolved
            return {"status": "success", "message": f"Opened {folder_name} in Finder", "path": resolved}
        return {"status": "error", "message": res.stderr.strip() or "Failed to open folder"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def create_folder(folder_name: str, location: Optional[str] = "Desktop") -> Dict[str, Any]:
    """Creates a new folder at the specified location (defaults to Desktop) and reveals it in Finder."""
    parent_dir = resolve_path(location or "Desktop")
    clean_name = folder_name.strip()
    target_path = os.path.join(parent_dir, clean_name)

    try:
        if os.path.exists(target_path):
            subprocess.run(["open", target_path], capture_output=True)
            return {"status": "success", "message": f"Folder '{clean_name}' already exists in {os.path.basename(parent_dir)}", "path": target_path}

        os.makedirs(target_path, exist_ok=True)
        subprocess.run(["open", target_path], capture_output=True)
        return {
            "status": "success",
            "message": f"Successfully created folder '{clean_name}' in {os.path.basename(parent_dir)}",
            "path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def rename_file_or_folder(current_name: str, new_name: str, location: Optional[str] = None) -> Dict[str, Any]:
    """Renames an existing folder or file on macOS using fuzzy name matching."""
    src_clean = current_name.strip()
    new_clean = new_name.strip()

    loc_dir = resolve_path(location) if location else None
    search_dirs = []
    if loc_dir and os.path.exists(loc_dir):
        search_dirs.append(loc_dir)

    desktop = os.path.expanduser("~/Desktop")
    if desktop not in search_dirs:
        search_dirs.append(desktop)

    # Also include subdirectories of Desktop (like 'New Folder for Text')
    try:
        for item in os.listdir(desktop):
            sub = os.path.join(desktop, item)
            if os.path.isdir(sub) and not item.startswith("."):
                search_dirs.append(sub)
    except Exception:
        pass

    for d in [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Documents"), os.path.expanduser("~")]:
        if d not in search_dirs:
            search_dirs.append(d)

    src_path = find_item_fuzzy(src_clean, search_dirs)
    if not src_path or not os.path.exists(src_path):
        return {"status": "error", "message": f"Could not find '{current_name}' to rename."}

    parent_dir = os.path.dirname(src_path)
    # If original file had an extension and new_name didn't specify one, preserve extension
    orig_ext = os.path.splitext(src_path)[1]
    new_ext = os.path.splitext(new_clean)[1]
    if orig_ext and not new_ext and not os.path.isdir(src_path):
        new_clean = new_clean + orig_ext

    dst_path = os.path.join(parent_dir, new_clean)
    if os.path.exists(dst_path) and os.path.abspath(dst_path) != os.path.abspath(src_path):
        return {"status": "error", "message": f"An item named '{new_clean}' already exists in {os.path.basename(parent_dir)}."}

    try:
        os.rename(src_path, dst_path)
        subprocess.run(["open", "-R", dst_path], capture_output=True)
        return {
            "status": "success",
            "message": f"Successfully renamed '{os.path.basename(src_path)}' to '{new_clean}' in {os.path.basename(parent_dir)}",
            "new_path": dst_path
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def move_file_or_folder(
    source: str,
    destination: str,
    source_location: Optional[str] = None
) -> Dict[str, Any]:
    """Moves a file, folder, multiple items, or category (e.g. screenshots, images, documents) into a target folder."""
    dest_resolved = resolve_path(destination)
    target_filename = None

    # Check if destination is a file path rather than directory (e.g. ends with an extension like .pdf)
    if not os.path.isdir(dest_resolved) and (os.path.splitext(dest_resolved)[1] or "." in os.path.basename(dest_resolved)):
        parent_dir = os.path.dirname(dest_resolved)
        if os.path.exists(parent_dir):
            dest_dir = parent_dir
            target_filename = os.path.basename(dest_resolved)
        else:
            dest_dir = dest_resolved
    else:
        dest_dir = dest_resolved

    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception as e:
            return {"status": "error", "message": f"Could not create destination directory: {e}"}

    src_dir = resolve_path(source_location or "Desktop") if source_location else None
    search_dirs = [src_dir] if src_dir else [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~")
    ]

    # Split comma-separated sources (e.g. "a.png, b.jpg" or "*.png, *.jpg, *.jpeg")
    raw_sources = [s.strip() for s in source.split(",") if s.strip()]
    if not raw_sources:
        return {"status": "error", "message": "No source files or folders specified to move."}

    files_to_move = []
    not_found = []

    for raw_src in raw_sources:
        clean_src = raw_src.strip()
        lower_src = clean_src.lower().replace("all ", "").replace("my ", "").strip()

        # 1. Category check
        matched_patterns = None
        if lower_src in CATEGORY_EXTENSIONS:
            matched_patterns = CATEGORY_EXTENSIONS[lower_src]
        elif any(w in lower_src for w in ["screenshot", "screenshots"]):
            matched_patterns = CATEGORY_EXTENSIONS["screenshots"]

        if matched_patterns:
            search_base = src_dir or os.path.expanduser("~/Desktop")
            found_any = False
            for pat in matched_patterns:
                for match_path in glob.glob(os.path.join(search_base, pat)):
                    if os.path.abspath(match_path) != os.path.abspath(dest_dir):
                        files_to_move.append(match_path)
                        found_any = True
            if not found_any:
                not_found.append(clean_src)
            continue

        # 2. Wildcard check (including path-prefixed wildcards like Desktop/Folder/*.pdf)
        if any(c in clean_src for c in ["*", "?", "["]):
            search_base = src_dir or os.path.expanduser("~/Desktop")
            pattern_file = clean_src
            if "/" in clean_src:
                dir_part = os.path.dirname(clean_src)
                search_base = resolve_path(dir_part)
                pattern_file = os.path.basename(clean_src)

            matches = glob.glob(os.path.join(search_base, pattern_file))
            valid_matches = [m for m in matches if os.path.abspath(m) != os.path.abspath(dest_dir)]
            if valid_matches:
                files_to_move.extend(valid_matches)
            else:
                not_found.append(clean_src)
            continue

        # 3. Fuzzy single item lookup
        matched_path = find_item_fuzzy(clean_src, search_dirs)
        if matched_path and os.path.abspath(matched_path) != os.path.abspath(dest_dir):
            files_to_move.append(matched_path)
        else:
            not_found.append(clean_src)

    seen = set()
    unique_files = []
    for f in files_to_move:
        abs_f = os.path.abspath(f)
        if abs_f not in seen:
            seen.add(abs_f)
            unique_files.append(abs_f)

    if not unique_files:
        if not_found:
            return {"status": "error", "message": f"Could not find {', '.join(not_found)} to move."}
        return {"status": "info", "message": "No matching items found to move."}

    moved_count = 0
    moved_names = []
    try:
        for item in unique_files:
            # If target_filename specified and only one file moved, rename to that target filename
            if target_filename and len(unique_files) == 1:
                target_path = os.path.join(dest_dir, target_filename)
            else:
                target_path = os.path.join(dest_dir, os.path.basename(item))

            if os.path.abspath(item) == os.path.abspath(target_path):
                continue
            shutil.move(item, target_path)
            moved_names.append(os.path.basename(target_path))
            moved_count += 1

        subprocess.run(["open", dest_dir], capture_output=True)
        dest_name = os.path.basename(dest_dir) or dest_dir

        if moved_count == 1:
            return {
                "status": "success",
                "message": f"Successfully moved '{moved_names[0]}' into {dest_name}",
                "destination": os.path.join(dest_dir, moved_names[0])
            }
        else:
            return {
                "status": "success",
                "message": f"Successfully moved {moved_count} items into {dest_name}",
                "moved_count": moved_count,
                "destination": dest_dir
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def delete_file_or_folder(
    target: str,
    location: Optional[str] = None
) -> Dict[str, Any]:
    """Safely moves a file, folder, multiple items, or pattern to the macOS Trash using Finder."""
    src_dir = resolve_path(location or "Desktop") if location else None
    search_dirs = [src_dir] if src_dir else [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~")
    ]

    # Split comma-separated targets
    raw_targets = [s.strip() for s in target.split(",") if s.strip()]
    if not raw_targets:
        return {"status": "error", "message": "No target file or folder specified to delete."}

    files_to_trash = []
    not_found = []

    for raw_target in raw_targets:
        clean_target = clean_folder_name(raw_target).strip().strip("'\"")
        lower_target = clean_target.lower().replace("all ", "").replace("my ", "").strip()

        # 1. Category check
        matched_patterns = None
        if lower_target in CATEGORY_EXTENSIONS:
            matched_patterns = CATEGORY_EXTENSIONS[lower_target]
        elif any(w in lower_target for w in ["screenshot", "screenshots"]):
            matched_patterns = CATEGORY_EXTENSIONS["screenshots"]

        if matched_patterns:
            search_base = src_dir or os.path.expanduser("~/Desktop")
            found_any = False
            for pat in matched_patterns:
                for match_path in glob.glob(os.path.join(search_base, pat)):
                    files_to_trash.append(match_path)
                    found_any = True
            if not found_any:
                not_found.append(clean_target)
            continue

        # 2. Wildcard check
        if any(c in clean_target for c in ["*", "?", "["]):
            search_base = src_dir or os.path.expanduser("~/Desktop")
            pattern_file = clean_target
            if "/" in clean_target:
                dir_part = os.path.dirname(clean_target)
                search_base = resolve_path(dir_part)
                pattern_file = os.path.basename(clean_target)
            matches = glob.glob(os.path.join(search_base, pattern_file))
            if matches:
                files_to_trash.extend(matches)
            else:
                not_found.append(clean_target)
            continue

        # 3. Fuzzy single item lookup
        matched_path = find_item_fuzzy(clean_target, search_dirs)
        if matched_path:
            files_to_trash.append(matched_path)
        else:
            not_found.append(clean_target)

    # De-duplicate
    seen = set()
    unique_files = []
    for f in files_to_trash:
        abs_f = os.path.abspath(f)
        if abs_f not in seen:
            seen.add(abs_f)
            unique_files.append(abs_f)

    if not unique_files:
        if not_found:
            return {"status": "error", "message": f"Could not find {', '.join(not_found)} to move to Trash."}
        return {"status": "info", "message": "No matching items found to move to Trash."}

    trashed_names = []
    failed_names = []

    for item in unique_files:
        # Protect against trashing system or home root directories
        norm_item = os.path.normpath(item)
        if norm_item in ["/", os.path.expanduser("~"), os.path.expanduser("~/Desktop"), os.path.expanduser("~/Documents"), os.path.expanduser("~/Downloads")]:
            return {"status": "error", "message": f"Cannot delete critical root directory: {item}"}

        escaped = item.replace('\\', '\\\\').replace('"', '\\"')
        scpt = f'tell application "Finder" to delete POSIX file "{escaped}"'
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            trashed_names.append(os.path.basename(item))
        else:
            # Fallback if Finder script fails
            try:
                scpt2 = f'tell application "Finder" to move POSIX file "{escaped}" to trash'
                res2 = subprocess.run(["osascript", "-e", scpt2], capture_output=True, text=True)
                if res2.returncode == 0:
                    trashed_names.append(os.path.basename(item))
                else:
                    failed_names.append(os.path.basename(item))
            except Exception:
                failed_names.append(os.path.basename(item))

    if trashed_names:
        if len(trashed_names) == 1:
            return {
                "status": "success",
                "message": f"Successfully moved '{trashed_names[0]}' to the macOS Trash.",
                "deleted": trashed_names
            }
        else:
            return {
                "status": "success",
                "message": f"Successfully moved {len(trashed_names)} items to the macOS Trash: {', '.join(trashed_names)}",
                "deleted": trashed_names
            }
    else:
        return {"status": "error", "message": f"Failed to move items to Trash: {', '.join(failed_names)}"}

def open_url(url: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """Opens a website in a browser."""
    clean_url = url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url

    try:
        if browser:
            target_browser = APP_ALIASES.get(browser.strip().lower(), browser.strip())
            res = subprocess.run(["open", "-a", target_browser, clean_url], capture_output=True, text=True)
        else:
            res = subprocess.run(["open", clean_url], capture_output=True, text=True)

        if res.returncode == 0:
            return {"status": "success", "url": clean_url, "browser": browser or "default"}
        return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def create_note(title: str, content: str) -> Dict[str, Any]:
    """Creates a formatted note in Apple Notes and brings it to the foreground."""
    clean_title = title.strip().replace("\\", "\\\\").replace('"', '\\"')
    clean_content = content.strip().replace("\\", "\\\\").replace('"', '\\"').replace("\n", "<br>")
    html_body = f"<h1>{clean_title}</h1><p>{clean_content}</p>"

    scpt = f'''
    tell application "Notes"
        activate
        make new note at folder "Notes" of default account with properties {{name:"{clean_title}", body:"{html_body}"}}
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "success", "title": title, "message": "Note created and displayed in Notes"}
        return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def search_google(query: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """Searches Google for a query and opens the search results."""
    encoded = urllib.parse.quote_plus(query.strip())
    url = f"https://www.google.com/search?q={encoded}"
    return open_url(url, browser)

def create_reminder(title: str) -> Dict[str, Any]:
    """Creates an item in Apple Reminders."""
    clean_title = title.strip().replace("\\", "\\\\").replace('"', '\\"')
    scpt = f'''
    tell application "Reminders"
        make new reminder with properties {{name:"{clean_title}"}}
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "success", "title": title, "message": "Reminder created"}
        return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def clipboard_action(action: str, text: Optional[str] = None) -> Dict[str, Any]:
    """Reads from or copies text to the macOS clipboard."""
    act = action.strip().lower()
    try:
        if act in ["copy", "write"]:
            if text is None:
                return {"status": "error", "message": "No text provided to copy"}
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return {"status": "success", "message": "Text copied to clipboard"}
        elif act in ["read", "paste", "get"]:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True)
            return {"status": "success", "clipboard_content": res.stdout}
        else:
            return {"status": "error", "message": f"Unknown action {action}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def take_screenshot() -> Dict[str, Any]:
    """Takes a screenshot and saves it to the user's Desktop."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.expanduser(f"~/Desktop/Screenshot_{timestamp}.png")
    try:
        res = subprocess.run(["/usr/sbin/screencapture", "-x", filepath], capture_output=True)
        if res.returncode == 0:
            return {"status": "success", "filepath": filepath, "message": "Screenshot saved to Desktop"}
        return {"status": "error", "message": "Failed to take screenshot"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def analyze_screen(query: Optional[str] = None) -> Dict[str, Any]:
    """Captures the user's screen and uses Gemini Vision to inspect, analyze, and point out UI elements, code, windows, or errors."""
    q = (query or "Ekranda nima ko'rinmoqda va qanday muhim ma'lumotlar bor?").strip()
    tmp_path = "/tmp/swan_screen.jpg"
    tmp_small = "/tmp/swan_screen_small.jpg"
    try:
        # Capture full display with cursor
        res = subprocess.run(["/usr/sbin/screencapture", "-x", "-C", "-t", "jpg", tmp_path], capture_output=True, timeout=5.0)
        if res.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {
                "status": "error",
                "message": "Ekran tasvirini olib bo'lmadi. Iltimos, macOS Sozlamalari -> Maxfiylik va Xavfsizlik -> Ekranni yozib olish (Screen Recording) ruxsatini tekshiring."
            }

        # Downscale for rapid transmission
        try:
            from PIL import Image
            img = Image.open(tmp_path)
            img.thumbnail((1280, 720))
            img.save(tmp_small, quality=75)
            with open(tmp_small, "rb") as f:
                img_bytes = f.read()
        except Exception:
            with open(tmp_path, "rb") as f:
                img_bytes = f.read()

        from google import genai
        from google.genai import types
        from config import config

        vision_client = genai.Client(api_key=config.api_key)
        system_prompt = (
            "Siz Swan nomli macOS AI agentisiz. Foydalanuvchining ekran tasvirini sinchiklab tahlil qiling. "
            f"Foydalanuvchi so'rovi: '{q}'. "
            "Ekranni diqqat bilan o'rganing: asosiy faol oyna, dasturlar, veb-sahifalar, xatoliklar (error), matn yoki kodlarni aniqlang. "
            "QAT'IY TALABLAR: "
            "1. Faqat toza, go'zal va adabiy O'ZBEK TILIDA javob bering. "
            "2. Ovozli yordamchi ravon o'qib berishi uchun yulduzchalar (**), tire (-), qavslar yoki kod belgilarini mutlaqo ishlatmang. "
            "3. Gaplar juda ixcham, ravon va mohiyatga yo'naltirilgan bo'lsin (ko'pi bilan 2 ta aniq va chiroyli gap). "
            "4. Javobni bevosita ko'ringan narsaning mohiyatidan boshlang (masalan: 'Ekranda Safari orqali YouTube sahifasi ochiq...', 'Ekranda dasturlash kodida xatolik ko'rinmoqda...')."
        )

        try:
            resp = vision_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    system_prompt
                ]
            )
        except Exception:
            resp = vision_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    system_prompt
                ]
            )
        return {
            "status": "success",
            "analysis": resp.text,
            "message": "Screen analyzed successfully"
        }
    except Exception as e:
        return {"status": "error", "message": f"Screen analysis failed: {e}"}
    finally:
        for p in (tmp_path, tmp_small):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

def execute_shell(command: str) -> Dict[str, Any]:
    """Executes a shell command (zsh/bash) on macOS to inspect, automate, run scripts, or manage the computer."""
    if not command or not command.strip():
        return {"status": "error", "message": "Command is empty"}
    clean_cmd = command.strip()
    try:
        res = subprocess.run(
            clean_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30.0,
            executable="/bin/zsh",
            cwd=os.path.expanduser("~")
        )
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        return {
            "status": "success" if res.returncode == 0 else "error",
            "returncode": res.returncode,
            "stdout": stdout[:3000] if stdout else "",
            "stderr": stderr[:1500] if stderr else "",
            "message": f"Command executed with exit code {res.returncode}"
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command timed out after 30 seconds"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def read_file(filepath: str, max_lines: int = 150) -> Dict[str, Any]:
    """Reads the text content of a file on the computer."""
    p = os.path.expanduser(filepath.strip())
    if not os.path.exists(p):
        return {"status": "error", "message": f"File does not exist: {filepath}"}
    if os.path.isdir(p):
        try:
            items = os.listdir(p)[:60]
            return {"status": "success", "is_directory": True, "items": items, "path": p}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(max_lines)]
            content = "".join(lines)
        return {"status": "success", "filepath": p, "content": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def write_file(filepath: str, content: str, mode: str = "w") -> Dict[str, Any]:
    """Creates or writes text content to a file on the user's computer."""
    p = os.path.expanduser(filepath.strip())
    parent_dir = os.path.dirname(p)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    try:
        write_mode = "a" if "append" in mode.lower() else "w"
        with open(p, write_mode, encoding="utf-8") as f:
            f.write(content)
        action_word = "appended to" if write_mode == "a" else "written to"
        return {"status": "success", "filepath": p, "message": f"Successfully {action_word} {p}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def applescript_exec(script: str) -> Dict[str, Any]:
    """Executes native AppleScript code to automate macOS apps (Safari, Finder, Notes, System Settings, etc.)."""
    clean_script = script.strip()
    try:
        res = subprocess.run(["osascript", "-e", clean_script], capture_output=True, text=True, timeout=15.0)
        if res.returncode == 0:
            return {"status": "success", "result": res.stdout.strip()}
        return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def switch_tab(
    tab_index: Optional[int] = None,
    tab_name: Optional[str] = None,
    action: Optional[str] = "switch",
    browser: Optional[str] = None
) -> Dict[str, Any]:
    """
    Switches between tabs, selects a tab by number or title, or manages tabs in browsers and tabbed apps on macOS.
    Supports Google Chrome, Safari, Brave, Arc, and general tabbed apps.
    """
    act = (action or "switch").strip().lower()
    clean_target = (tab_name or "").strip().lower()

    # 1. Determine target browser / app
    target_browser = None
    if browser:
        b_low = browser.strip().lower()
        if "chrome" in b_low:
            target_browser = "Google Chrome"
        elif "safari" in b_low:
            target_browser = "Safari"
        elif "brave" in b_low:
            target_browser = "Brave Browser"
        elif "arc" in b_low:
            target_browser = "Arc"
        else:
            target_browser = browser.strip()

    if not target_browser:
        detect_script = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
            set allApps to name of every application process
        end tell
        return frontApp & "|" & (allApps contains "Google Chrome") & "|" & (allApps contains "Safari") & "|" & (allApps contains "Arc") & "|" & (allApps contains "Brave Browser")
        '''
        try:
            res = subprocess.run(["osascript", "-e", detect_script], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                parts = res.stdout.strip().split("|")
                front_app = parts[0].strip()
                has_chrome = len(parts) > 1 and parts[1].strip().lower() == "true"
                has_safari = len(parts) > 2 and parts[2].strip().lower() == "true"
                has_arc = len(parts) > 3 and parts[3].strip().lower() == "true"
                has_brave = len(parts) > 4 and parts[4].strip().lower() == "true"

                if front_app in ["Google Chrome", "Safari", "Arc", "Brave Browser"]:
                    target_browser = front_app
                elif has_chrome:
                    target_browser = "Google Chrome"
                elif has_safari:
                    target_browser = "Safari"
                elif has_arc:
                    target_browser = "Arc"
                elif has_brave:
                    target_browser = "Brave Browser"
                else:
                    target_browser = front_app
        except Exception:
            target_browser = "Google Chrome"

    target_browser = target_browser or "Google Chrome"

    # 2. Google Chrome or Brave Browser
    if target_browser in ["Google Chrome", "Brave Browser"]:
        ascript = f'''
        tell application "{target_browser}"
            activate
            if (count of windows) = 0 then
                return "error:No windows open in {target_browser}"
            end if
            set win to window 1
            set totalTabs to count of tabs of win

            if "{act}" is "list" then
                set res to ""
                repeat with i from 1 to totalTabs
                    set res to res & (i as string) & ": " & (title of tab i of win) & linefeed
                end repeat
                return "list:" & res
            else if "{act}" is "new" then
                tell win to make new tab
                return "success:Opened new tab"
            else if "{act}" is "close" then
                close active tab of win
                return "success:Closed tab"
            else if "{act}" is "next" then
                set cur to active tab index of win
                if cur < totalTabs then
                    set active tab index of win to (cur + 1)
                else
                    set active tab index of win to 1
                end if
                return "success:Switched to tab " & (active tab index of win) & " (" & (title of active tab of win) & ")"
            else if "{act}" is "previous" or "{act}" is "prev" then
                set cur to active tab index of win
                if cur > 1 then
                    set active tab index of win to (cur - 1)
                else
                    set active tab index of win to totalTabs
                end if
                return "success:Switched to tab " & (active tab index of win) & " (" & (title of active tab of win) & ")"
            end if

            -- Search by name/title
            if "{clean_target}" is not "" then
                repeat with i from 1 to totalTabs
                    set tTitle to (title of tab i of win) as string
                    set tUrl to (URL of tab i of win) as string
                    ignoring case
                        if (tTitle contains "{clean_target}") or (tUrl contains "{clean_target}") then
                            set active tab index of win to i
                            return "success:Switched to tab " & (i as string) & " (" & tTitle & ")"
                        end if
                    end ignoring
                end repeat
            end if

            -- Switch by 1-indexed tab index
            set targetIdx to {int(tab_index) if tab_index is not None else 0}
            if targetIdx > 0 then
                if targetIdx > totalTabs then
                    set targetIdx to totalTabs
                end if
                set active tab index of win to targetIdx
                return "success:Switched to tab " & (targetIdx as string) & " (" & (title of active tab of win) & ")"
            end if

            return "error:Please specify a tab number (e.g. 1, 2, 3) or tab name."
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", ascript], capture_output=True, text=True, timeout=5.0)
            out = res.stdout.strip()
            if out.startswith("success:"):
                return {"status": "success", "message": out[8:].strip(), "browser": target_browser}
            elif out.startswith("list:"):
                tabs = [line.strip() for line in out[5:].splitlines() if line.strip()]
                return {"status": "success", "tabs": tabs, "browser": target_browser, "message": f"Found {len(tabs)} tabs in {target_browser}"}
            elif out.startswith("error:"):
                return {"status": "error", "message": out[6:].strip(), "browser": target_browser}
            return {"status": "success", "message": f"Switched tab in {target_browser}", "browser": target_browser}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 3. Safari
    elif target_browser == "Safari":
        ascript = f'''
        tell application "Safari"
            activate
            if (count of windows) = 0 then
                return "error:No windows open in Safari"
            end if
            set win to window 1
            set totalTabs to count of tabs of win

            if "{act}" is "list" then
                set res to ""
                repeat with i from 1 to totalTabs
                    set res to res & (i as string) & ": " & (name of tab i of win) & linefeed
                end repeat
                return "list:" & res
            else if "{act}" is "new" then
                tell win to make new tab
                return "success:Opened new tab"
            else if "{act}" is "close" then
                close current tab of win
                return "success:Closed tab"
            else if "{act}" is "next" then
                set cur to index of current tab of win
                if cur < totalTabs then
                    set current tab of win to tab (cur + 1) of win
                else
                    set current tab of win to tab 1 of win
                end if
                return "success:Switched to tab " & (index of current tab of win) & " (" & (name of current tab of win) & ")"
            else if "{act}" is "previous" or "{act}" is "prev" then
                set cur to index of current tab of win
                if cur > 1 then
                    set current tab of win to tab (cur - 1) of win
                else
                    set current tab of win to tab totalTabs of win
                end if
                return "success:Switched to tab " & (index of current tab of win) & " (" & (name of current tab of win) & ")"
            end if

            -- Search by name
            if "{clean_target}" is not "" then
                repeat with i from 1 to totalTabs
                    set tName to (name of tab i of win) as string
                    set tUrl to (URL of tab i of win) as string
                    ignoring case
                        if (tName contains "{clean_target}") or (tUrl contains "{clean_target}") then
                            set current tab of win to tab i of win
                            return "success:Switched to tab " & (i as string) & " (" & tName & ")"
                        end if
                    end ignoring
                end repeat
            end if

            -- Switch by index
            set targetIdx to {int(tab_index) if tab_index is not None else 0}
            if targetIdx > 0 then
                if targetIdx > totalTabs then
                    set targetIdx to totalTabs
                end if
                set current tab of win to tab targetIdx of win
                return "success:Switched to tab " & (targetIdx as string) & " (" & (name of current tab of win) & ")"
            end if

            return "error:Please specify a tab number (e.g. 1, 2, 3) or tab name."
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", ascript], capture_output=True, text=True, timeout=5.0)
            out = res.stdout.strip()
            if out.startswith("success:"):
                return {"status": "success", "message": out[8:].strip(), "browser": "Safari"}
            elif out.startswith("list:"):
                tabs = [line.strip() for line in out[5:].splitlines() if line.strip()]
                return {"status": "success", "tabs": tabs, "browser": "Safari", "message": f"Found {len(tabs)} tabs in Safari"}
            elif out.startswith("error:"):
                return {"status": "error", "message": out[6:].strip(), "browser": "Safari"}
            return {"status": "success", "message": "Switched tab in Safari", "browser": "Safari"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 4. Fallback for other apps (Cmd + 1..9, or Ctrl+Tab)
    else:
        try:
            if tab_index and 1 <= tab_index <= 9:
                key_script = f'''
                tell application "{target_browser}" to activate
                delay 0.1
                tell application "System Events"
                    keystroke "{tab_index}" using command down
                end tell
                '''
                subprocess.run(["osascript", "-e", key_script], check=True, timeout=3.0)
                return {"status": "success", "message": f"Switched to tab {tab_index} in {target_browser}", "browser": target_browser}
            elif act == "next":
                key_script = f'''
                tell application "{target_browser}" to activate
                delay 0.1
                tell application "System Events"
                    key code 48 using control down
                end tell
                '''
                subprocess.run(["osascript", "-e", key_script], check=True, timeout=3.0)
                return {"status": "success", "message": f"Switched to next tab in {target_browser}", "browser": target_browser}
            elif act in ["previous", "prev"]:
                key_script = f'''
                tell application "{target_browser}" to activate
                delay 0.1
                tell application "System Events"
                    key code 48 using {{control down, shift down}}
                end tell
                '''
                subprocess.run(["osascript", "-e", key_script], check=True, timeout=3.0)
                return {"status": "success", "message": f"Switched to previous tab in {target_browser}", "browser": target_browser}
            elif act == "new":
                key_script = f'''
                tell application "{target_browser}" to activate
                delay 0.1
                tell application "System Events"
                    keystroke "t" using command down
                end tell
                '''
                subprocess.run(["osascript", "-e", key_script], check=True, timeout=3.0)
                return {"status": "success", "message": f"Opened new tab in {target_browser}", "browser": target_browser}
            elif act == "close":
                key_script = f'''
                tell application "{target_browser}" to activate
                delay 0.1
                tell application "System Events"
                    keystroke "w" using command down
                end tell
                '''
                subprocess.run(["osascript", "-e", key_script], check=True, timeout=3.0)
                return {"status": "success", "message": f"Closed tab in {target_browser}", "browser": target_browser}
            return {"status": "error", "message": f"Unsupported action '{act}' for {target_browser}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

def switch_mode(target_mode: str) -> Dict[str, Any]:
    """Switches the assistant between 'command' mode and 'chat' mode."""
    mode_lower = target_mode.strip().lower()
    if "chat" in mode_lower:
        mode = "chat"
    elif "command" in mode_lower or "swan" in mode_lower or "system" in mode_lower:
        mode = "command"
    else:
        mode = mode_lower

    if mode_change_callback:
        mode_change_callback(mode)

    return {"status": "success", "active_mode": mode}

def get_current_time() -> Dict[str, Any]:
    """Returns the user's exact current local date, time, and timezone information."""
    now = datetime.now().astimezone()
    time_24h = now.strftime("%H:%M")
    time_12h = now.strftime("%I:%M %p").lstrip("0")
    tz_offset = now.strftime("%z")
    tz_formatted = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if len(tz_offset) == 5 else f"UTC{tz_offset}"
    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    return {
        "status": "success",
        "local_time_24h": time_24h,
        "local_time_12h": time_12h,
        "timezone": tz_formatted,
        "day_of_week": day_name,
        "local_date": date_str,
        "summary": f"{time_24h} ({time_12h}), {day_name}, {date_str} ({tz_formatted})"
    }

def system_control(action: str, value: Optional[str] = None) -> Dict[str, Any]:
    """Controls system volume, media, or queries system status."""
    action_lower = action.strip().lower()

    try:
        if action_lower in ["volume_up", "louder"]:
            subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 12)"])
            return {"status": "success", "message": "Increased volume"}
        elif action_lower in ["volume_down", "quieter", "lower"]:
            subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 12)"])
            return {"status": "success", "message": "Decreased volume"}
        elif action_lower in ["mute"]:
            subprocess.run(["osascript", "-e", "set volume output muted true"])
            return {"status": "success", "message": "Muted audio"}
        elif action_lower in ["unmute"]:
            subprocess.run(["osascript", "-e", "set volume output muted false"])
            return {"status": "success", "message": "Unmuted audio"}
        elif action_lower in ["play_pause", "play", "pause"]:
            # Intelligently toggle Spotify if active, or fall back to Apple Music
            if ensure_spotify_running(timeout=0.5):
                return spotify_control("pause" if action_lower == "pause" else ("play" if action_lower == "play" else "play_pause"))
            subprocess.run(["osascript", "-e", 'tell application "Music" to playpause'])
            return {"status": "success", "message": "Toggled music playback"}
        elif action_lower in ["battery", "battery_status"]:
            res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
            output = res.stdout.strip()
            match = re.search(r'(\d+)%', output)
            batt_pct = match.group(1) if match else "unknown"
            charging = "charging" in output or "AC Power" in output
            return {"status": "success", "battery_percentage": batt_pct, "is_charging": charging, "raw": output}
        elif action_lower in ["time", "current_time"]:
            return get_current_time()
        else:
            return {"status": "unknown_action", "action": action}
    except Exception as e:
        return {"status": "error", "message": str(e)}

SPOTIFY_CLI_PATH = "/Applications/Spotify.app/Contents/MacOS/spotify_cli"

def ensure_spotify_running(timeout: float = 2.5) -> bool:
    """Ensures Spotify is running and its IPC channel is ready."""
    if os.path.exists(SPOTIFY_CLI_PATH):
        try:
            res = subprocess.run([SPOTIFY_CLI_PATH, "status", "--format", "json"], capture_output=True, text=True, timeout=0.8)
            if res.returncode == 0 and json.loads(res.stdout).get("running"):
                return True
        except Exception:
            pass

    try:
        subprocess.run(["open", "-a", "Spotify"], capture_output=True)
    except Exception:
        pass

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.15)
        if os.path.exists(SPOTIFY_CLI_PATH):
            try:
                res = subprocess.run([SPOTIFY_CLI_PATH, "status", "--format", "json"], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and json.loads(res.stdout).get("running"):
                    return True
            except Exception:
                pass
    return False

def spotify_control(action: str = "play", query: Optional[str] = None, volume_level: Optional[int] = None) -> Dict[str, Any]:
    """
    Controls Spotify playback on macOS with instantaneous response:
    - action='play': Resumes playback or searches & plays specific query (song, artist, playlist, genre).
    - action='pause': Pauses playback.
    - action='play_pause': Toggles play/pause.
    - action='next': Skips to next track.
    - action='previous': Plays previous track.
    - action='now_playing': Returns currently playing track info.
    - action='volume': Sets volume (0-100).
    """
    action_lower = (action or "play").lower().strip()
    ensure_spotify_running()
    use_cli = os.path.exists(SPOTIFY_CLI_PATH)

    # 1. PLAY / RESUME
    if action_lower in ["play", "resume", "start", "play_pause"]:
        # If toggling without query and already playing
        if action_lower == "play_pause":
            if use_cli:
                try:
                    np = subprocess.run([SPOTIFY_CLI_PATH, "now-playing", "--format", "json"], capture_output=True, text=True, timeout=0.6)
                    if np.returncode == 0 and json.loads(np.stdout).get("currently_playing", {}).get("is_playing"):
                        subprocess.run([SPOTIFY_CLI_PATH, "pause"], capture_output=True)
                        return {"status": "success", "message": "Paused Spotify playback"}
                except Exception:
                    pass

        # If a query is provided, search and play that track/artist/playlist
        if query and query.strip():
            q = query.strip()
            # Clean common filler words
            q_clean = re.sub(r'^(play|put on|start)\s+', '', q, flags=re.IGNORECASE).strip()
            q_clean = re.sub(r'\s+on spotify$', '', q_clean, flags=re.IGNORECASE).strip()
            if not q_clean:
                q_clean = q

            # Curated popular genres & vibes
            curated_map = {
                "liked": "spotify:collection:tracks",
                "liked songs": "spotify:collection:tracks",
                "my songs": "spotify:collection:tracks",
                "my music": "spotify:collection:tracks",
                "favorites": "spotify:collection:tracks",
                "top hits": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
                "popular": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
                "lofi": "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
                "lo-fi": "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
                "chill": "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
                "relax": "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
                "rock": "spotify:playlist:37i9dQZF1DX1rVvRgNX2YR",
                "classic rock": "spotify:playlist:37i9dQZF1DX1rVvRgNX2YR",
                "jazz": "spotify:playlist:37i9dQZF1DXbITWG1ZJKYt",
                "rap": "spotify:playlist:37i9dQZF1DX0XUsuxWHRQd",
                "hip hop": "spotify:playlist:37i9dQZF1DX0XUsuxWHRQd",
                "classical": "spotify:playlist:37i9dQZF1DWWEW2C3f4v6V",
                "piano": "spotify:playlist:37i9dQZF1DWWEW2C3f4v6V",
                "workout": "spotify:playlist:37i9dQZF1DX76Wlfdnj7AP",
                "gym": "spotify:playlist:37i9dQZF1DX76Wlfdnj7AP",
                "study": "spotify:playlist:37i9dQZF1DX4sWSpwq3LiO",
                "focus": "spotify:playlist:37i9dQZF1DX4sWSpwq3LiO",
                "sleep": "spotify:playlist:37i9dQZF1DWZd79rJ6a7lp"
            }

            matched_uri = None
            for key, uri in curated_map.items():
                if key == q_clean.lower() or key in q_clean.lower():
                    matched_uri = uri
                    break

            if matched_uri and use_cli:
                subprocess.run([SPOTIFY_CLI_PATH, "play", matched_uri], capture_output=True)
                return {"status": "success", "message": f"Playing {q_clean} on Spotify", "uri": matched_uri}

            # Search Spotify catalog via CLI
            if use_cli:
                try:
                    search_res = subprocess.run(
                        [SPOTIFY_CLI_PATH, "search", q_clean, "--limit", "1", "--format", "json"],
                        capture_output=True, text=True, timeout=2.5
                    )
                    if search_res.returncode == 0 and search_res.stdout.strip():
                        data = json.loads(search_res.stdout)
                        order = data.get("categories_order", [])
                        item_to_play = None
                        item_type = "content"

                        # Try the top category reported by Spotify search
                        for cat in order:
                            items = data.get(cat, [])
                            if items:
                                item_to_play = items[0]
                                item_type = cat[:-1] if cat.endswith("s") else cat
                                break

                        # Fallback across all categories if order was empty
                        if not item_to_play:
                            for cat in ["tracks", "artists", "playlists", "albums"]:
                                items = data.get(cat, [])
                                if items:
                                    item_to_play = items[0]
                                    item_type = cat[:-1]
                                    break

                        if item_to_play and "uri" in item_to_play:
                            target_uri = item_to_play["uri"]
                            item_name = item_to_play.get("name", q_clean)
                            artists = ", ".join(item_to_play.get("artists", []))
                            desc = f"'{item_name}'" + (f" by {artists}" if artists else "")

                            subprocess.run([SPOTIFY_CLI_PATH, "play", target_uri], capture_output=True)
                            return {
                                "status": "success",
                                "message": f"Playing {desc} on Spotify",
                                "name": item_name,
                                "uri": target_uri,
                                "type": item_type
                            }
                except Exception as e:
                    print(f"[WARN] Spotify CLI search error: {e}", flush=True)

            # Fallback to AppleScript search URI
            try:
                enc = urllib.parse.quote(q_clean)
                subprocess.run(["open", f"spotify:search:{enc}"])
                time.sleep(0.5)
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'])
                return {"status": "success", "message": f"Opened '{q_clean}' in Spotify"}
            except Exception as e:
                return {"status": "error", "message": f"Failed to search Spotify: {e}"}

        # If no query: resume current track or start Liked Songs
        if use_cli:
            try:
                res = subprocess.run([SPOTIFY_CLI_PATH, "resume"], capture_output=True, text=True, timeout=1.0)
                if res.returncode != 0:
                    subprocess.run([SPOTIFY_CLI_PATH, "play", "spotify:collection:tracks"], capture_output=True)
                return {"status": "success", "message": "Resumed Spotify playback"}
            except Exception:
                pass

        # AppleScript fallback
        try:
            scpt = '''
            tell application "Spotify"
                play
                return (player state as string)
            end tell
            '''
            res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
            return {"status": "success", "message": "Resumed Spotify playback", "state": res.stdout.strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 2. PAUSE / STOP
    elif action_lower in ["pause", "stop"]:
        if use_cli:
            try:
                subprocess.run([SPOTIFY_CLI_PATH, "pause"], capture_output=True)
                return {"status": "success", "message": "Paused Spotify"}
            except Exception:
                pass
        try:
            subprocess.run(["osascript", "-e", 'tell application "Spotify" to pause'])
            return {"status": "success", "message": "Paused Spotify"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 3. NEXT TRACK
    elif action_lower in ["next", "skip", "next_track"]:
        if use_cli:
            try:
                subprocess.run([SPOTIFY_CLI_PATH, "next"], capture_output=True)
                time.sleep(0.3)
                np = subprocess.run([SPOTIFY_CLI_PATH, "now-playing", "--format", "json"], capture_output=True, text=True)
                track_desc = ""
                if np.returncode == 0:
                    d = json.loads(np.stdout)
                    track_desc = d.get("currently_playing", {}).get("description", "")
                return {"status": "success", "message": f"Skipped to next track: {track_desc}" if track_desc else "Skipped to next track"}
            except Exception:
                pass
        try:
            scpt = '''
            tell application "Spotify"
                next track
                delay 0.3
                return (name of current track) & " by " & (artist of current track)
            end tell
            '''
            res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
            return {"status": "success", "message": f"Skipped to next track: {res.stdout.strip()}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 4. PREVIOUS TRACK
    elif action_lower in ["previous", "back", "prev", "previous_track"]:
        if use_cli:
            try:
                subprocess.run([SPOTIFY_CLI_PATH, "previous"], capture_output=True)
                return {"status": "success", "message": "Playing previous track"}
            except Exception:
                pass
        try:
            subprocess.run(["osascript", "-e", 'tell application "Spotify" to previous track'])
            return {"status": "success", "message": "Playing previous track"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 5. NOW PLAYING / STATUS
    elif action_lower in ["now_playing", "current", "status", "info"]:
        if use_cli:
            try:
                np = subprocess.run([SPOTIFY_CLI_PATH, "now-playing", "--format", "json"], capture_output=True, text=True)
                if np.returncode == 0:
                    d = json.loads(np.stdout)
                    cp = d.get("currently_playing", {})
                    return {
                        "status": "success",
                        "description": cp.get("description", ""),
                        "is_playing": cp.get("is_playing", False),
                        "uri": cp.get("uri", "")
                    }
            except Exception:
                pass
        try:
            scpt = '''
            tell application "Spotify"
                return {name of current track, artist of current track, album of current track, player state as string}
            end tell
            '''
            res = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
            return {"status": "success", "raw": res.stdout.strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # 6. VOLUME
    elif action_lower in ["volume", "set_volume"]:
        lvl = volume_level if volume_level is not None else 60
        lvl = max(0, min(100, lvl))
        if use_cli:
            try:
                subprocess.run([SPOTIFY_CLI_PATH, "volume", str(lvl)], capture_output=True)
                return {"status": "success", "message": f"Spotify volume set to {lvl}%"}
            except Exception:
                pass
        try:
            subprocess.run(["osascript", "-e", f'tell application "Spotify" to set sound volume to {lvl}'])
            return {"status": "success", "message": f"Spotify volume set to {lvl}%"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    else:
        return {"status": "unknown_action", "action": action}

# Dispatch table
TOOL_HANDLERS = {
    "open_app": open_app,
    "close_app": close_app,
    "quit_app": close_app,
    "open_folder": open_folder,
    "create_folder": create_folder,
    "rename_file_or_folder": rename_file_or_folder,
    "rename_folder": rename_file_or_folder,
    "move_file_or_folder": move_file_or_folder,
    "move_folder": move_file_or_folder,
    "move_files": move_file_or_folder,
    "delete_file_or_folder": delete_file_or_folder,
    "delete_folder": delete_file_or_folder,
    "delete_file": delete_file_or_folder,
    "remove_folder": delete_file_or_folder,
    "remove_file": delete_file_or_folder,
    "trash_folder": delete_file_or_folder,
    "trash_file": delete_file_or_folder,
    "spotify_control": spotify_control,
    "play_music": spotify_control,
    "control_spotify": spotify_control,
    "open_url": open_url,
    "create_note": create_note,
    "search_google": search_google,
    "create_reminder": create_reminder,
    "clipboard_action": clipboard_action,
    "take_screenshot": take_screenshot,
    "analyze_screen": analyze_screen,
    "see_screen": analyze_screen,
    "inspect_screen": analyze_screen,
    "check_screen": analyze_screen,
    "look_at_screen": analyze_screen,
    "execute_shell": execute_shell,
    "run_terminal_command": execute_shell,
    "run_bash": execute_shell,
    "read_file": read_file,
    "write_file": write_file,
    "create_file": write_file,
    "applescript_exec": applescript_exec,
    "run_applescript": applescript_exec,
    "switch_tab": switch_tab,
    "switch_browser_tab": switch_tab,
    "change_tab": switch_tab,
    "select_tab": switch_tab,
    "tab_control": switch_tab,
    "switch_mode": switch_mode,
    "system_control": system_control,
    "get_current_time": get_current_time,
    "dismiss_assistant": dismiss_assistant,
    "dismiss": dismiss_assistant,
    "hide_assistant": dismiss_assistant,
    "disappear": dismiss_assistant,
    "close_assistant": dismiss_assistant,
    "remember_user_fact": remember_user_fact,
    "remember_fact": remember_user_fact,
    "get_user_memory": get_user_memory
}

async def execute_tool_call(name: str, args: dict) -> dict:
    """Executes a tool call by name and returns result dictionary."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"status": "error", "message": f"Unknown tool '{name}'"}
    try:
        import inspect
        if inspect.iscoroutinefunction(handler):
            result = await handler(**args)
        else:
            result = await asyncio.to_thread(handler, **args)
        if not isinstance(result, dict):
            result = {"status": "success", "result": str(result) if result is not None else "OK"}
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_jarvis_tools() -> list[types.Tool]:
    """Returns the Tool declaration list for Gemini Live API."""
    declarations = [
        types.FunctionDeclaration(
            name="open_app",
            description="Opens any application on macOS or downloaded web apps (e.g. YouTube, ChatGPT, Google Gemini, ElevenLabs, GitHub, Vercel, Safari, Google Chrome, Terminal, Notes, Finder, Calculator, Music, Spotify).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "app_name": types.Schema(
                        type="STRING",
                        description="The name of the application or downloaded web app to launch, e.g. 'YouTube', 'ChatGPT', 'Google Gemini', 'Safari', 'Notes'."
                    )
                },
                required=["app_name"]
            )
        ),
        types.FunctionDeclaration(
            name="close_app",
            description="Quits or closes an application or the active window on macOS (e.g. 'close Safari', 'quit Chrome', 'close Telegram', 'exit Notes', 'close this window', 'quit active app').",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "app_name": types.Schema(
                        type="STRING",
                        description="The name of the application to quit (e.g. 'Safari', 'Chrome', 'Telegram', 'Notes'), or 'current' / 'window' to close the frontmost app or window."
                    ),
                    "force": types.Schema(
                        type="BOOLEAN",
                        description="Optional boolean to force quit if application does not respond."
                    )
                }
            )
        ),
        types.FunctionDeclaration(
            name="open_folder",
            description="Opens a folder, directory, or location in macOS Finder (e.g. 'open Downloads', 'open Desktop', 'open Documents', 'open Projects folder').",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "folder_path": types.Schema(
                        type="STRING",
                        description="The name or path of the folder to open, e.g. 'Downloads', 'Desktop', 'Documents', 'Projects'."
                    )
                },
                required=["folder_path"]
            )
        ),
        types.FunctionDeclaration(
            name="create_folder",
            description="Creates a new folder or directory at the specified location (e.g. 'create a folder named Invoices on Desktop', 'create folder Research in Documents').",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "folder_name": types.Schema(
                        type="STRING",
                        description="The name of the new folder to create, e.g. 'Invoices', 'Research', 'Projects'."
                    ),
                    "location": types.Schema(
                        type="STRING",
                        description="Optional parent directory location, e.g. 'Desktop', 'Downloads', 'Documents', or a custom path. Defaults to 'Desktop'."
                    )
                },
                required=["folder_name"]
            )
        ),
        types.FunctionDeclaration(
            name="rename_file_or_folder",
            description="Renames an existing folder or file on macOS (e.g. 'rename folder Invoices on Desktop to Receipts', 'rename notes.txt to ideas.txt in Downloads').",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "current_name": types.Schema(
                        type="STRING",
                        description="The current name of the file or folder to rename."
                    ),
                    "new_name": types.Schema(
                        type="STRING",
                        description="The new name for the file or folder."
                    ),
                    "location": types.Schema(
                        type="STRING",
                        description="Optional parent directory where the item is located (e.g. 'Desktop', 'Downloads', 'Documents')."
                    )
                },
                required=["current_name", "new_name"]
            )
        ),
        types.FunctionDeclaration(
            name="move_file_or_folder",
            description="Moves a file, folder, or matching set of files (such as all screenshots) from one folder into another (e.g. 'move all screenshots from Desktop into Screenshots folder', 'move invoice.pdf from Downloads to Documents').",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "source": types.Schema(
                        type="STRING",
                        description="The name, wildcard pattern, or category of items to move, e.g. 'screenshots', 'report.pdf', '*.png'."
                    ),
                    "destination": types.Schema(
                        type="STRING",
                        description="The target folder name or destination path, e.g. 'Screenshots', 'Documents', 'Archive'."
                    ),
                    "source_location": types.Schema(
                        type="STRING",
                        description="Optional folder where the items are currently located (e.g. 'Desktop', 'Downloads'). Defaults to 'Desktop'."
                    )
                },
                required=["source", "destination"]
            )
        ),
        types.FunctionDeclaration(
            name="delete_file_or_folder",
            description="Safely moves a file or folder to the macOS Trash (e.g. 'delete folder Temp on Desktop', 'remove test.txt in Downloads', 'move project folder to trash'). Items can be restored from Trash if needed.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target": types.Schema(
                        type="STRING",
                        description="The name, pattern, or path of the file or folder to delete/move to Trash (e.g. 'Temp', 'test.txt', 'Old Projects')."
                    ),
                    "location": types.Schema(
                        type="STRING",
                        description="Optional parent directory location where the item is located (e.g. 'Desktop', 'Downloads', 'Documents'). Defaults to 'Desktop'."
                    )
                },
                required=["target"]
            )
        ),
        types.FunctionDeclaration(
            name="open_url",
            description="Opens a website URL in Safari or another browser on macOS.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(
                        type="STRING",
                        description="The website address or domain to open, e.g. 'example.com', 'google.com', 'github.com'."
                    ),
                    "browser": types.Schema(
                        type="STRING",
                        description="Optional browser name, e.g. 'Safari' or 'Google Chrome'. Defaults to Safari."
                    )
                },
                required=["url"]
            )
        ),
        types.FunctionDeclaration(
            name="create_note",
            description="Creates a note with title and text content in Apple Notes and brings Notes to the front. Use this whenever the user asks to write a note, take notes, or write a story/document in Notes.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "title": types.Schema(
                        type="STRING",
                        description="The title of the note."
                    ),
                    "content": types.Schema(
                        type="STRING",
                        description="The body content/story of the note."
                    )
                },
                required=["title", "content"]
            )
        ),
        types.FunctionDeclaration(
            name="search_google",
            description="Performs a Google web search and opens the results page in the browser.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="The search query string."
                    ),
                    "browser": types.Schema(
                        type="STRING",
                        description="Optional browser name, e.g. 'Safari'."
                    )
                },
                required=["query"]
            )
        ),
        types.FunctionDeclaration(
            name="create_reminder",
            description="Adds a new reminder in Apple Reminders.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "title": types.Schema(
                        type="STRING",
                        description="The reminder task description."
                    )
                },
                required=["title"]
            )
        ),
        types.FunctionDeclaration(
            name="clipboard_action",
            description="Reads the current macOS clipboard or copies text to the clipboard.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "action": types.Schema(
                        type="STRING",
                        description="'copy' to copy text to clipboard, or 'read' to read current clipboard."
                    ),
                    "text": types.Schema(
                        type="STRING",
                        description="Text to copy (when action is 'copy')."
                    )
                },
                required=["action"]
            )
        ),
        types.FunctionDeclaration(
            name="take_screenshot",
            description="Takes a screenshot of the Mac screen and saves it directly to the Desktop.",
            parameters=types.Schema(
                type="OBJECT",
                properties={}
            )
        ),
        types.FunctionDeclaration(
            name="switch_mode",
            description="Switches between 'command' mode (system actions) and 'chat' mode (conversational partner).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target_mode": types.Schema(
                        type="STRING",
                        description="The mode to switch to: 'command' or 'chat'."
                    )
                },
                required=["target_mode"]
            )
        ),
        types.FunctionDeclaration(
            name="system_control",
            description="Controls macOS system settings: volume (volume_up, volume_down, mute, unmute), media (play_pause), battery level, or current time.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "action": types.Schema(
                        type="STRING",
                        description="'volume_up', 'volume_down', 'mute', 'unmute', 'play_pause', 'battery', or 'time'."
                    )
                },
                required=["action"]
            )
        ),
        types.FunctionDeclaration(
            name="get_current_time",
            description="Gets the user's current local time, date, day of week, and timezone. ALWAYS call this tool whenever the user asks for the time, what time it is, or today's date.",
            parameters=types.Schema(
                type="OBJECT",
                properties={}
            )
        ),
        types.FunctionDeclaration(
            name="spotify_control",
            description=(
                "Controls Spotify music playback on macOS. "
                "Can play any specific song, artist, album, playlist, or genre (e.g. 'play Bohemian Rhapsody on Spotify', 'play The Weeknd', 'play lofi beats', 'play liked songs', 'play Turkish pop'), "
                "or resume playback, pause/stop music, skip to next track, play previous track, or check currently playing song."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "action": types.Schema(
                        type="STRING",
                        description="Action to perform: 'play' (resume or play search query), 'pause', 'next', 'previous', 'now_playing', or 'volume'."
                    ),
                    "query": types.Schema(
                        type="STRING",
                        description="Optional song, artist, album, playlist, or genre to search and play (e.g. 'Bohemian Rhapsody', 'The Weeknd', 'lofi beats', 'workout', 'liked songs', 'Turkish pop')."
                    ),
                    "volume_level": types.Schema(
                        type="INTEGER",
                        description="Optional volume percentage between 0 and 100 when action is 'volume'."
                    )
                },
                required=["action"]
            )
        ),
        types.FunctionDeclaration(
            name="analyze_screen",
            description=(
                "Captures and analyzes the user's screen in real-time using multimodal AI vision. "
                "Use this tool whenever the user says 'look at my screen', 'what is on my screen', 'can you see this', "
                "'analyze my screen', 'analyse my screen', 'scan my screen', 'see my screen', 'analyze this error', 'ekranga qara', 'ekranda nima bor', or asks questions about visible windows, text, code, or UI elements."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="Specific question, focus, or instructions about what to analyze on screen (e.g. 'What is the error on the screen?', 'Summarize this article', 'What app is open?')."
                    )
                }
            )
        ),
        types.FunctionDeclaration(
            name="execute_shell",
            description=(
                "Executes a shell command (zsh/bash) directly on macOS. "
                "Use this to inspect files, check system status, run developer tools (git, python, curl, brew, npm), automate tasks, or execute multi-step plans."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "command": types.Schema(
                        type="STRING",
                        description="The exact shell command line to run, e.g. 'git status', 'ls -la ~/Projects', 'python3 script.py', 'curl ifconfig.me'."
                    )
                },
                required=["command"]
            )
        ),
        types.FunctionDeclaration(
            name="read_file",
            description="Reads the text content of a file or lists files in a directory on the user's computer.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "filepath": types.Schema(
                        type="STRING",
                        description="The path to the file or directory to read, e.g. '~/Desktop/notes.txt', '~/Projects/app.py'."
                    ),
                    "max_lines": types.Schema(
                        type="INTEGER",
                        description="Maximum number of lines to read (default: 150)."
                    )
                },
                required=["filepath"]
            )
        ),
        types.FunctionDeclaration(
            name="write_file",
            description="Creates, overwrites, or appends text to a file on the user's computer.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "filepath": types.Schema(
                        type="STRING",
                        description="The path where the file should be saved or edited, e.g. '~/Desktop/todo.txt'."
                    ),
                    "content": types.Schema(
                        type="STRING",
                        description="The full text content to write into the file."
                    ),
                    "mode": types.Schema(
                        type="STRING",
                        description="'w' to create/overwrite, 'a' to append."
                    )
                },
                required=["filepath", "content"]
            )
        ),
        types.FunctionDeclaration(
            name="applescript_exec",
            description="Executes AppleScript on macOS to automate UI interactions, Safari tabs, Finder windows, or System Settings.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "script": types.Schema(
                        type="STRING",
                        description="The AppleScript code snippet to run."
                    )
                },
                required=["script"]
            )
        ),
        types.FunctionDeclaration(
            name="switch_tab",
            description=(
                "Switches or selects tabs in web browsers (Google Chrome, Safari, Brave, Arc) or tabbed applications on macOS. "
                "Use this tool whenever the user asks to switch or select tabs (e.g. 'switch to the 1st tab', 'switch to 3rd tab', "
                "'1-tabga o't', '3-tabga o't', 'keyingi tabga o't', 'switch to YouTube tab', 'next tab', 'close this tab', 'list open tabs')."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "tab_index": types.Schema(
                        type="INTEGER",
                        description="The 1-based index of the tab to switch to (e.g. 1 for first tab, 2 for second, 3 for third tab, etc.)."
                    ),
                    "tab_name": types.Schema(
                        type="STRING",
                        description="Optional keyword or title to search and select among open tabs (e.g. 'YouTube', 'Google', 'IELTS', 'Docs')."
                    ),
                    "action": types.Schema(
                        type="STRING",
                        description="Optional action: 'switch' (default), 'next', 'previous', 'new', 'close', or 'list'."
                    ),
                    "browser": types.Schema(
                        type="STRING",
                        description="Optional specific browser name: 'Google Chrome', 'Safari', 'Arc', 'Brave Browser'."
                    )
                }
            )
        ),
        types.FunctionDeclaration(
            name="dismiss_assistant",
            description=(
                "Immediately hides and dismisses the assistant from the screen. "
                "Call this tool whenever the user tells the assistant to disappear, go away, hide, close, dismiss, "
                "or says 'yo'qol', 'yashirin', 'ket', 'xayr', 'dam ol', 'yo'q bo'l', 'ekrandan ket'."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "reason": types.Schema(
                        type="STRING",
                        description="Optional reason for dismissing (e.g. 'user requested dismissal')."
                    )
                }
            )
        ),
        types.FunctionDeclaration(
            name="remember_user_fact",
            description=(
                "Stores a permanent fact, preference, or rule about the owner (Ahmet) into Swan's long-term memory. "
                "Call this whenever the user says 'eslab qol', 'yodingda saqla', 'remember that', or gives a personal preference/detail."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "fact": types.Schema(
                        type="STRING",
                        description="The fact or preference to remember about the user."
                    ),
                    "category": types.Schema(
                        type="STRING",
                        description="Optional category: 'preference', 'identity', 'work', 'music', 'general'."
                    )
                },
                required=["fact"]
            )
        ),
        types.FunctionDeclaration(
            name="get_user_memory",
            description="Retrieves the owner's profile, saved preferences, and long-term memory facts.",
            parameters=types.Schema(
                type="OBJECT",
                properties={}
            )
        )
    ]
    return [types.Tool(function_declarations=declarations)]
