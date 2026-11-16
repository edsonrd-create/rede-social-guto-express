"""Initialize this service's fresh volume subdirectory, then drop privileges."""
import os
from pathlib import Path
import runpy

if __name__=='__main__':
    os.umask(0o077)
    if os.geteuid()==0:
        directory=Path('/data/app')
        if directory.is_symlink(): raise RuntimeError('Volume path cannot be a symlink.')
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chown(directory,10001,10001)
        os.chmod(directory,0o700)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    if os.geteuid()==0: raise RuntimeError('Application must not run as root.')
    print('Guto Express Social app_uid='+str(os.geteuid()),flush=True)
    runpy.run_module('run_service',run_name='__main__')
