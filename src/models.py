import hashlib
import os
import json
from subprocess import check_call, check_output

import dparse.updater
from poetry.factory import Factory as PoetryFactory
from poetry.core.semver.version import Version as PoetryVersion


class DepFile:
    def __init__(self, filename):
        self.filename = filename
        self.dir = os.path.dirname(self.filename)
        self.settings = get_config_settings()
        self._load()

    def _load(self):
        with open(self.filename, "r") as f:
            self.content = f.read()

        self.dparser = self._get_dparser()

    def _get_dparser(self):
        parser = dparse.parse(content=self.content, path=self.filename)
        if not parser.is_valid:
            raise Exception("Unable to parse {filename}".format(filename=self.filename))
        return parser

    @property
    def lockfile(self):
        return None

    @property
    def _outdated(self):
        # Cache these results
        if not hasattr(self, "__outdated"):
            pip = which_pip(self.dir)
            output = check_output(
                [pip, "list", "--local", "--outdated", "--format=json"]
            )
            self.__outdated = json.loads(output)

        return self.__outdated

    def _get_outdated_version_of_dependency(self, name):
        for item in self._outdated:
            if item["name"].lower() == name.lower():
                return item["latest_version"]
        return None

    def update_dependency(self, dependency, constraint):
        """Lockfiles don't need to implement this since the whole thing is updated at once"""
        raise NotImplementedError

    def get_dependencies(self):
        """Return dependencies.io formatted list of manifest dependencies"""
        raise NotImplementedError

    def fingerprint(self):
        return hashlib.md5(self.content.encode("utf-8")).hexdigest()


class Requirements(DepFile):
    def update_dependency(self, dependency, constraint):
        dparse_dependency = [
            x for x in self.dparser.dependencies if x.key == dependency
        ][0]
        updated_content = dparse.updater.RequirementsTXTUpdater.update(
            content=self.content,
            dependency=dparse_dependency,
            version=constraint,
            spec="",
        )  # spec in constraint
        with open(self.filename, "w+") as f:
            f.write(updated_content)
        self._load()

    def get_dependencies(self):
        output = {
            "current": {
                "dependencies": {},
            },
            "updated": {
                "dependencies": {},
            },
        }

        deps = self.dparser.dependencies

        for dep in deps:

            current_constraint = str(dep.specs) or "*"
            output["current"]["dependencies"][dep.key] = {
                "source": dep.source,
                "constraint": current_constraint,
            }

            latest = self._get_outdated_version_of_dependency(dep.key)
            if latest and not dep.specs.contains(latest):
                updated_constraint = f"=={latest}"  # TODO could guess prefix here
                output["updated"]["dependencies"][dep.key] = {
                    "source": dep.source,
                    "constraint": updated_constraint,
                }

        return output


class Pipfile(DepFile):
    def update_dependency(self, dependency, constraint):
        dparse_dependency = [
            x for x in self.dparser.dependencies if x.key == dependency
        ][0]
        updated_content = dparse.updater.PipfileUpdater.update(
            content=self.content,
            dependency=dparse_dependency,
            version=constraint,
            spec="",
        )  # spec in constraint
        with open(self.filename, "w+") as f:
            f.write(updated_content)
        self._load()

    @property
    def lockfile(self):
        return PipfileLock(os.path.join(self.dir, "Pipfile.lock"))

    def get_dependencies(self):
        output = {
            "current": {
                "dependencies": {},
            },
            "updated": {
                "dependencies": {},
            },
        }

        deps = [
            d
            for d in self.dparser.dependencies
            if d.section in self.settings["pipfile_sections"]
        ]

        for dep in deps:

            current_constraint = str(dep.specs) or "*"
            output["current"]["dependencies"][dep.key] = {
                "source": dep.source,
                "constraint": current_constraint,
            }

            latest = self._get_outdated_version_of_dependency(dep.key)
            if latest and not dep.specs.contains(latest):
                updated_constraint = f"=={latest}"  # TODO could guess prefix here
                output["updated"]["dependencies"][dep.key] = {
                    "source": dep.source,
                    "constraint": updated_constraint,
                }

        return output


class PipfileLock(DepFile):
    def fingerprint(self):
        # Pipfile.lock stores its own hash but it's of the Pipfile, so we
        # need our own hash of the Pipfile.lock.
        #
        # If we compute our own (hashing the file) then we're likely to get
        # get misleading results since Pipfile.lock contains info about
        # the platform the command was run on. This will differ from the user
        # to us (and between users/machines/etc.) so we can't rely on that
        # as the fingerprint for the update. If we did, we'd likely send
        # a bunch of updates that only change the meta info in Pipfile.lock.

        # Thus we'll use just part of the Pipfile.lock contents -- everyting
        # but the top-level "_meta" section.
        pipfile_data = json.loads(self.content)
        del pipfile_data["_meta"]
        sha = hashlib.sha256()
        sha.update(json.dumps(pipfile_data).encode("utf8"))
        return "sha256:{hexdigest}".format(hexdigest=sha.hexdigest())

    def update(self):
        check_call(["pipenv", "update"], cwd=(self.dir or None))
        self._load()

    def get_dependencies(self, direct_dependencies=[]):
        """Return dependencies.io formatted list of lockfile dependencies"""
        dependencies = {}

        deps = [
            d
            for d in self.dparser.dependencies
            if d.section in self.settings["pipfilelock_sections"]
        ]

        for dep in deps:
            dependencies[dep.key] = {
                "source": dep.source,
                "version": {"name": str(dep.specs).lstrip("=")},
            }
            if direct_dependencies:
                dependencies[dep.key]["is_transitive"] = (
                    True if dep.key not in direct_dependencies else False
                )

        return dependencies


class PoetryBase(DepFile):
    def _get_dparser(self):
        """dparse doesn't support this yet"""
        return None

    @property
    def _poetry(self):
        return PoetryFactory().create_poetry(self.dir)


class PoetryPyproject(PoetryBase):
    @property
    def lockfile(self):
        return PoetryLock(os.path.join(self.dir, "poetry.lock"))

    def update_dependency(self, dependency, constraint):
        options = ["--dev"] if dependency in self._poetry.local_config.get("dev-dependencies", {}) else []
        # TODO what to do if new constraint breaks another, or python version?
        # just a failed update for now...
        check_call(["poetry", "add", dependency + constraint] + options)
        self._load()

    def get_dependencies(self):
        output = {
            "current": {
                "dependencies": {},
            },
            "updated": {
                "dependencies": {},
            },
        }

        for dep in (self._poetry.package.requires + self._poetry.package.dev_requires):
            output["current"]["dependencies"][dep.pretty_name] = {
                "source": dep.source_url or "pypi",
                "constraint": dep.pretty_constraint,
            }

            latest = self._get_outdated_version_of_dependency(dep.pretty_name)
            if latest:
                try:
                    poetry_version = PoetryVersion.parse(latest)
                except Exception as e:
                    print(e)
                    continue

                if not dep.constraint.allows(poetry_version):
                    output["updated"]["dependencies"][dep.pretty_name] = {
                        "source": dep.source_url or "pypi",
                        "constraint": f"=={latest}"  # TODO could guess prefix here,
                    }

        return output


class PoetryLock(PoetryBase):
    def update(self):
        check_call(["poetry", "update"], cwd=(self.dir or None))
        self._load()

    def get_dependencies(self, direct_dependencies=[]):
        dependencies = {}

        for dep in self._poetry.locker.lock_data["package"]:
            dependencies[dep["name"]] = {
                "source": dep.get("source", {}).get("type", "pypi"),  # crude for now
                "version": {"name": dep["version"]},
            }
            if direct_dependencies:
                dependencies[dep["name"]]["is_transitive"] = (
                    True if dep["name"] not in direct_dependencies else False
                )

        return dependencies


def load_dependency_file(path):
    if path.endswith("Pipfile"):
        return Pipfile(path)
    elif path.endswith("Pipfile.lock"):
        return PipfileLock(path)
    elif path.endswith("pyproject.toml"):
        return PoetryPyproject(path)
    elif path.endswith("poetry.lock"):
        return PoetryLock(path)
    else:
        return Requirements(path)


def load_dependency_files(path):
    """
    Recursively (if necessary) gather all the manifests referenced by the starting_path and return as list
    :param starting_path:
    :return:
    """
    f = load_dependency_file(path)
    files = [f]

    # recursively call
    if f.dparser:
        for file in f.dparser.resolved_files:
            more_manifests = load_dependency_files(file)
            files.extend(more_manifests)

    return files


def get_config_settings():
    """"Parse configuration settings from the environment variables set in the container"""
    conf = {}
    # Pipfiles are expected to have all the requirements of a project for development, production, testing, etc all
    # listed in a single file, unlike requirements.txt convention where production and development requirements are
    # often split into different files.  Thus, it is necessary to have the ability to configure which sections of the
    # file should be considered for management by dependencies.io.  The default will be to include both of the standard
    # sections of the Pipfile.  This setting can be configured to eliminate a section or to possibly add a custom
    # section name.
    #
    # pipfile_sections:
    #    - packages
    #    - dev-packages
    # pipfilelock_sections:
    #    - default
    #    - develop
    SETTING_PIPFILE_SECTIONS = os.getenv(
        "DEPS_SETTING_PIPFILE_SECTIONS", '["packages", "dev-packages"]'
    )
    conf["pipfile_sections"] = json.loads(SETTING_PIPFILE_SECTIONS)

    SETTING_PIPFILELOCK_SECTIONS = os.getenv(
        "DEPS_SETTING_PIPFILELOCK_SECTIONS", '["default", "develop"]'
    )
    conf["pipfilelock_sections"] = json.loads(SETTING_PIPFILELOCK_SECTIONS)

    return conf


def which_pip(search_directory):
    SETTING_PIP_PATH = os.getenv("DEPS_SETTING_PIP_PATH", "")
    if SETTING_PIP_PATH:
        if os.path.exists(SETTING_PIP_PATH):
            return SETTING_PIP_PATH
        else:
            raise Exception(
                f"pip_path ({SETTING_PIP_PATH}) from settings does not exist"
            )

    to_try = [".venv", "env", ".env"]

    try:
        pipenv_venv = check_output(["pipenv", "--venv"], cwd=(search_directory or None))
        to_try.append(pipenv_venv.decode("utf-8").strip())
    except Exception:  # was CalledProcessError, but poetry seems to have monkeypatched that and broke
        pass

    try:
        poetry_env = check_output(["poetry", "env", "info", "-p"], cwd=(search_directory or None))
        to_try.append(poetry_env.decode("utf-8").strip())
    except Exception:
        pass

    for t in to_try:
        pip_path = os.path.join(search_directory, t, "bin", "pip")
        if os.path.exists(pip_path):
            return pip_path

    return "pip"
