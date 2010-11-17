#  Copyright (c) 2009-2010, Cloud Matrix Pty. Ltd.
#  All rights reserved; available under the terms of the BSD License.
"""

  myppy.envs.base:  base MyppyEnv class definition.

"""

from __future__ import with_statement

import os
import sys
import subprocess
import shutil
import sqlite3
import errno
import urlparse
import urllib2
from functools import wraps

from myppy import util


from myppy.recipes import base as _base_recipes


class MyppyEnv(object):
    """A myppy environment.

    This class represents a myppy environment installed in the given root
    directory.  It's useful for running commands within that environment.
    Handy methods:

        * init():       initialize (or re-initialize) the myppy environment
        * clean():      clean up temporary and build-related files
        * do():         execute a subprocess within the environment
        * install():    install a given recipe into the environment
        * uninstall():  uninstall a recipe from the environment

    """
 
    DB_NAME = os.path.join("local","myppy.db")

    def __init__(self,rootdir):
        if not isinstance(rootdir,unicode):
            rootdir = rootdir.decode(sys.getfilesystemencoding())
        self.rootdir = os.path.abspath(rootdir)
        self.builddir = os.path.join(self.rootdir,"build")
        self.cachedir = os.path.join(self.rootdir,"cache")
        self.env = os.environ.copy()
        self._add_env_path("PATH",os.path.join(self.PREFIX,"bin"))
        self._has_db_lock = 0
        if not os.path.exists(self.rootdir):
            os.makedirs(self.rootdir)
        self._db = sqlite3.connect(os.path.join(self.rootdir,self.DB_NAME),
                                   isolation_level=None)
        self._initdb()

    def __enter__(self):
        if not self._has_db_lock:
            self._db.execute("BEGIN IMMEDIATE TRANSACTION")
        self._has_db_lock += 1

    def __exit__(self,exc_type,exc_value,exc_traceback):
        if exc_type is not None:
            self._has_db_lock -= 1
            if not self._has_db_lock:
                self._db.execute("ROLLBACK TRANSACTION")
        else:
            self._has_db_lock -= 1
            if not self._has_db_lock:
                self._db.execute("COMMIT TRANSACTION")

    def _add_env_path(self,key,path):
        """Add an entry to list of paths in an envionment variable."""
        PATH = self.env.get(key,"")
        if PATH:
            self.env[key] = path + ":" + PATH
        else:
            self.env[key] = path

    DEPENDENCIES = ["python27","py_pip","py_myppy"]

    @property
    def PREFIX(self):
        return os.path.join(self.rootdir,"local")

    @property
    def PYTHON_EXECUTABLE(self):
        return os.path.join(self.PREFIX,"bin","python")

    @property
    def PYTHON_HEADERS(self):
        return os.path.join(self.PREFIX,"include","python2.7")

    @property
    def PYTHON_LIBRARY(self):
        return os.path.join(self.PREFIX,"lib","python2.7.so")

    @property
    def SITE_PACKAGES(self):
        return os.path.join(self.PREFIX,"lib","python2.7","site-packages")

    def init(self):
        """Build the base myppy python environment."""
        for dep in self.DEPENDENCIES:
            self.install(dep)
        
    def clean(self):
        """Clean out temporary built files and the like."""
        shutil.rmtree(self.builddir)
        shutil.rmtree(self.cachedir)

    def do(self,*cmdline,**kwds):
        """Execute the given command within this myppy environment."""
        env = self.env.copy()
        env.update(kwds.pop("env",{}))
        subprocess.check_call(cmdline,env=env,**kwds)

    def bt(self,*cmdline,**kwds):
        """Execute the command within this myppy environment, return stdout.

        "bt" is short for "backticks"; hopefully its use is obvious to shell
        scripters and the like.
        """
        env = self.env.copy()
        env.update(kwds.pop("env",{}))
        p = subprocess.Popen(cmdline,stdout=subprocess.PIPE,env=env,**kwds)
        output = p.stdout.read()
        retcode = p.wait()
        if retcode != 0:
            raise subprocess.CalledProcessError(retcode,cmdline)
        return output

    def is_installed(self,recipe):
        q = "SELECT filepath FROM installed_files WHERE recipe=?"\
            " LIMIT 1"
        return (self._db.execute(q,(recipe,)).fetchone() is not None)
  
    def install(self,recipe):
        """Install the named recipe into this myppy env."""
        if not self.is_installed(recipe):
            r = self.load_recipe(recipe)
            for dep in r.DEPENDENCIES:
                if dep != recipe:
                    self.install(dep)
            print "FETCHING", recipe
            r.fetch()
            with self:
                print "BUILDING", recipe
                r.build()
                print "INSTALLING", recipe
                r.install()
                files = list(self.find_new_files())
                self.fixup_files(recipe,files)
                self.record_files(recipe,files)
                print "INSTALLED", recipe

    def uninstall(self,recipe):
        """Uninstall the named recipe from this myppy env."""
        # TODO: remove things depending on it
        with self:
            q = "SELECT filepath FROM installed_files WHERE recipe=?"\
                " ORDER BY filepath DESC"
            files = [r[0] for r in self._db.execute(q,(recipe,))]
            q = "DELETE FROM installed_files WHERE recipe=?"
            self._db.execute(q,(recipe,))
            for file in files:
                assert util.relpath(file) == file
                filepath = os.path.join(self.rootdir,file)
                if filepath.endswith(os.sep):
                    util.prune_dir(filepath)
                else:
                    os.unlink(filepath)
                    dirpath = os.path.dirname(filepath) + os.sep
                    if not os.listdir(dirpath):
                        q = "SELECT * FROM installed_files WHERE filepath=?"
                        if not self._is_oldfile(dirpath):
                            util.prune_dir(dirpath)
                
    def load_recipe(self,recipe):
        return getattr(_base_recipes,recipe)(self)

    def _is_tempfile(self,path):
        for excl in (self.builddir,self.cachedir,):
            if path == excl or path.startswith(excl + os.sep):
                return True
        if os.path.basename(path) == "myppy.db":
            return True
        return False

    def _is_oldfile(self,file):
        file = file[len(self.rootdir)+1:]
        assert util.relpath(file) == file
        assert os.path.exists(os.path.join(self.rootdir,file))
        q = "SELECT * FROM installed_files WHERE filepath=?"
        if not self._db.execute(q,(file,)).fetchone():
            return False
        return True
 
    def find_new_files(self):
        for (dirpath,dirnms,filenms) in os.walk(self.rootdir):
            if self._is_tempfile(dirpath):
                dirnms[:] = []
            else:
                if not filenms:
                    if not self._is_oldfile(filepath):
                        yield dirpath + os.sep
                else:
                    for filenm in filenms:
                        filepath = os.path.join(dirpath,filenm)
                        if not self._is_tempfile(filepath):
                            if not self._is_oldfile(filepath):
                                yield filepath

    def fixup_files(self,recipe,files):
        assert files, "recipe '%s' didn't install any files" % (recipe,)

    def record_files(self,recipe,files):
        for file in files:
            file = file[len(self.rootdir)+1:]
            assert util.relpath(file) == file
            assert os.path.exists(os.path.join(self.rootdir,file))
            self._db.execute("INSERT INTO installed_files VALUES (?,?)",
                             (recipe,file,))

    def _initdb(self):
        self._db.execute("CREATE TABLE IF NOT EXISTS installed_files ("
                         "  recipe STRING NOT NULL,"
                         "  filepath STRING NOT NULL"
                         ")")

    def fetch(self,url,md5=None):
        """Fetch the file at the given URL, using cached version if possible."""
        cachedir = os.environ.get("MYPPY_DOWNLOAD_CACHE",self.cachedir)
        if cachedir:
            if not os.path.isabs(cachedir[0]):
                cachedir = os.path.join(self.rootdir,cachedir)
            if not os.path.isdir(cachedir):
                os.makedirs(cachedir)
        nm = os.path.basename(urlparse.urlparse(url).path)
        cachefile = os.path.join(cachedir,nm)
        if md5 is not None and os.path.exists(cachefile):
            if md5 != util.md5file(cachefile):
                os.unlink(cachefile)
        if not os.path.exists(cachefile):
            print "DOWNLOADING", url
            fIn = urllib2.urlopen(url)
            try:
                 with open(cachefile,"wb") as fOut:
                    shutil.copyfileobj(fIn,fOut)
            finally:
                fIn.close()
        if md5 is not None and md5 != util.md5file(cachefile):
            raise RuntimeError("corrupted download: %s" % (url,))
        return cachefile
