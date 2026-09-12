import os
import sys

def get_bundle_dir() -> str:
    """Returns the base directory for bundled static assets."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path: str) -> str:
    """Locate a static read-only asset (templates, models, sounds, icons)."""
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
