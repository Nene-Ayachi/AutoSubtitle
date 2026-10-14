"""Expose optional NVIDIA wheels to this process only, without changing system PATH."""
import os
import sysconfig
from pathlib import Path

_dll_handles = []
if os.name == 'nt':
    site = Path(sysconfig.get_path('purelib'))
    for library in ('cublas', 'cudnn'):
        directory = site / 'nvidia' / library / 'bin'
        if directory.is_dir():
            _dll_handles.append(os.add_dll_directory(str(directory)))
            os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')
