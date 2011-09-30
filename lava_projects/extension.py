# Copyright (C) 2010, 2011 Linaro Limited
#
# Author: Zygmunt Krynicki <zygmunt.krynicki@linaro.org>
#
# This file is part of LAVA Server.
#
# LAVA Server is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License version 3
# as published by the Free Software Foundation
#
# LAVA Server is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with LAVA Server.  If not, see <http://www.gnu.org/licenses/>.

from lava_server.extension import LavaServerExtension


class ProjectExtension(LavaServerExtension):
    """
    Extension adding project support
    """

    @property
    def app_name(self):
        return "lava_projects"

    @property
    def name(self):
        return "Projects"

    @property
    def main_view_name(self):
        return "lava.project.root"

    @property
    def description(self):
        return "Project support for LAVA"

    @property
    def version(self):
        import lava_projects
        import versiontools
        return versiontools.format_version(lava_projects.__version__, hint=lava_projects)
