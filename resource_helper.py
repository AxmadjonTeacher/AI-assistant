import os
import sys

def get_bundle_dir() -> str:
    """Returns the base directory for bundled static assets."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS') and os.path.exists(sys._MEIPASS):
            return sys._MEIPASS
        # macOS app bundle: sys.executable is in Contents/MacOS/Swan
        # Static resources are placed in Contents/Resources
        macos_dir = os.path.dirname(sys.executable)
        contents_dir = os.path.dirname(macos_dir)
        resources_dir = os.path.join(contents_dir, "Resources")
        if os.path.exists(resources_dir):
            return resources_dir
        frameworks_dir = os.path.join(contents_dir, "Frameworks")
        if os.path.exists(frameworks_dir):
            return frameworks_dir
        return macos_dir
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path: str) -> str:
    """Locate a static read-only asset (templates, models, sounds, icons)."""
    if getattr(sys, 'frozen', False):
        macos_dir = os.path.dirname(sys.executable)
        contents_dir = os.path.dirname(macos_dir)
        for sub in ["Resources", "Frameworks", "MacOS"]:
            cand = os.path.join(contents_dir, sub, relative_path)
            if os.path.exists(cand):
                return cand
        if hasattr(sys, '_MEIPASS'):
            cand = os.path.join(sys._MEIPASS, relative_path)
            if os.path.exists(cand):
                return cand

    bundle_dir = get_bundle_dir()
    primary = os.path.join(bundle_dir, relative_path)
    if os.path.exists(primary):
        return primary
    dev_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
    if os.path.exists(dev_path):
        return dev_path
    cwd_path = os.path.join(os.getcwd(), relative_path)
    if os.path.exists(cwd_path):
        return cwd_path
    return primary

def get_data_dir() -> str:
    """Directory for mutable user files (swan_settings.json, swan_memory.json)."""
    if getattr(sys, 'frozen', False):
        path = os.path.expanduser("~/Library/Application Support/Swan")
        os.makedirs(path, exist_ok=True)
        return path
    return os.path.dirname(os.path.abspath(__file__))

def get_data_path(filename: str) -> str:
    """Locate or return a writable path for user data files."""
    return os.path.join(get_data_dir(), filename)
