# pyi_runtime_hook.py
# Runs inside the frozen bundle before the app starts.
# Sets the correct matplotlib backend and Qt binding for PySide6.
import os
os.environ.setdefault('MPLBACKEND', 'QtAgg')
os.environ.setdefault('QT_API', 'pyside6')
