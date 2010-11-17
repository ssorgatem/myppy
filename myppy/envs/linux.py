#  Copyright (c) 2009-2010, Cloud Matrix Pty. Ltd.
#  All rights reserved; available under the terms of the BSD License.

from __future__ import with_statement

import os

from myppy.envs import base

from myppy.recipes import linux as _linux_recipes


class MyppyEnv(base.MyppyEnv):

    def __init__(self,rootdir):
        super(MyppyEnv,self).__init__(rootdir)
        self.env["APBUILD_STATIC_LIBGCC"] = "1"
        self.env["AUTOPACKAGE_FRONTEND"] = "apkg-ttyfe"
        self.env["CC"] = "apgcc"
        self.env["CXX"] = "apg++"
        self._add_env_path("PKG_CONFIG_PATH",os.path.join(self.PREFIX,
                                                          "lib/pkgconfig"))

    DEPENDENCIES = ["apbuild","patchelf"]
    DEPENDENCIES.extend(base.MyppyEnv.DEPENDENCIES)

    def load_recipe(self,recipe):
        try:
            r = getattr(_linux_recipes,recipe)
        except AttributeError:
            rbase = super(MyppyEnv,self).load_recipe(recipe).__class__
            rsuprnm = rbase.__bases__[0].__name__
            rsupr = self.load_recipe(rsuprnm).__class__
            class r(rbase,rsupr):
                pass
            r.__name__ = rbase.__name__
            r.__module__ = _linux_recipes.__name__
            setattr(_linux_recipes,recipe,r)
        return r(self)

