import hashlib
import os
import json
from subprocess import check_call, check_output, CalledProcessError

import dparse.updater


class Manifest:
    REQUIREMENTS = 'requirements.txt'
    PIPFILE = 'Pipfile'
    PIPFILE_LOCK = 'Pipfile.lock'

    def __init__(self, filename):
        self.filename = filename
        if filename.endswith(self.PIPFILE):
            self.type = self.PIPFILE
            self.filewriter = dparse.updater.PipfileUpdater
        elif filename.endswith(self.PIPFILE_LOCK):
            self.type = self.PIPFILE_LOCK
            self.filewriter = dparse.updater.PipfileLockUpdater
        else:
            self.type = self.REQUIREMENTS
            self.filewriter = dparse.updater.RequirementsTXTUpdater

        self._parse()

        self.outdated = []
        self._get_outdated()

        self.conf = get_config_settings()

    def _parse(self):
        with open(self.filename, 'r') as f:
            self.content = f.read()

        self.parser = dparse.parse(content=self.content, path=self.filename)

        if not self.parser.is_valid:
            raise Exception('Unable to parse {filename}'.format(filename=self.filename))

    @property
    def _pip(self):
        if not hasattr(self, "__pip"):
            # only need to check for this once, on first request
            pip = which_pip(os.path.dirname(self.filename))
            self.__pip = pip
        return self.__pip

    def _get_outdated(self):
        output = check_output([self._pip, "list", "--local", "--outdated", "--format=json"])
        self.outdated = json.loads(output)

    @classmethod
    def collect_manifests(cls, starting_path):
        """
        Recursively (if necessary) gather all the manifests referenced by the starting_path and return as list
        :param starting_path:
        :return:
        """
        manifests = []
        m = Manifest(starting_path)
        manifests.append(m)

        # recursively call
        files = m.parser.resolved_files
        for file in files:
            more_manifests = Manifest.collect_manifests(file)
            manifests.extend(more_manifests)
        return manifests

    @property
    def lockfile(self):
        if self.type == self.PIPFILE:
            return LockFile('Pipfile.lock')
        return None

    def raw_dependencies(self):
        return self.parser.dependencies

    def dependencies(self):
        if self.type == self.PIPFILE:
            return [d for d in self.raw_dependencies() if d.section in self.conf['pipfile_sections']]
        if self.type == self.PIPFILE_LOCK:
            return [d for d in self.raw_dependencies() if d.section in self.conf['pipfilelock_sections']]

        return self.raw_dependencies()

    def get_outdated_version_of_dependency(self, name):
        for item in self.outdated:
            if item["name"].lower() == name.lower():
                return item["latest_version"]
        return None

    def dio_dependencies(self):
        "Return dependencies.io formatted list of manifest dependencies"
        output = {
            "current": {
                "dependencies": {},
            },
            "updated": {
                "dependencies": {},
            },
        }

        for dep in self.dependencies():

            current_constraint = str(dep.specs) or "*"
            output["current"]["dependencies"][dep.key] = {
                'source': dep.source,
                'constraint': current_constraint,
            }

            latest = self.get_outdated_version_of_dependency(dep.key)
            if latest and not dep.specs.contains(latest):
                updated_constraint = f"=={latest}"  # TODO could guess prefix here
                output["updated"]["dependencies"][dep.key] = {
                    'source': dep.source,
                    'constraint': updated_constraint,
                }

        # final_data = {
        #     'manifests': {
        #         path.relpath('/repo/', manifest_path): dependencies
        #     }
        # }
        #
        # for p in dependency_file.resolved_files:
        #     # -r includes
        #     final_data.update(collect_manifest_dependencies(p))
        #
        # return final_data

        return output

    def fingerprint(self):
        return hashlib.md5(self.content.encode('utf-8')).hexdigest()

    def updater(self, content, dependency, version, spec):
        return self.filewriter.update(content=content, dependency=dependency, version=version, spec=spec)


class LockFile(Manifest):
    def native_update(self, dep=None):
        print("Using the native tools to update the lockfile")
        if self.type == self.PIPFILE_LOCK:
            if dep:
                check_call(["pipenv", "update", "--clear", dep])
            else:
                check_call(["pipenv", "update", "--clear"])
            self._parse()

    def dio_dependencies(self, direct_dependencies=None):
        "Return dependencies.io formatted list of lockfile dependencies"
        dependencies = {}
        for dep in self.dependencies():
            dependencies[dep.key] = {
                'source': dep.source,
                'version': {'name': str(dep.specs).lstrip("=")},
            }
            if direct_dependencies:
                dependencies[dep.key]['is_transitive'] = True if dep.key not in direct_dependencies else False

        return dependencies

    def fingerprint(self):
        if self.type == self.PIPFILE_LOCK:
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
            with open(self.filename, 'r') as f:
                pipfile_data = json.load(f)
            del(pipfile_data['_meta'])
            sha = hashlib.sha256()
            sha.update(json.dumps(pipfile_data).encode('utf8'))
            return "sha256:{hexdigest}".format(hexdigest=sha.hexdigest())

        return super(LockFile, self).fingerprint()


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
    SETTING_PIPFILE_SECTIONS = os.getenv("DEPS_SETTING_PIPFILE_SECTIONS", '["packages", "dev-packages"]')
    # print("DEPS_SETTING_PIPFILE_SECTIONS = {setting}".format(setting=SETTING_PIPFILE_SECTIONS))
    conf['pipfile_sections'] = json.loads(SETTING_PIPFILE_SECTIONS)

    SETTING_PIPFILELOCK_SECTIONS = os.getenv("DEPS_SETTING_PIPFILELOCK_SECTIONS", '["default", "develop"]')
    # print("DEPS_SETTING_PIPFILELOCK_SECTIONS = {setting}".format(setting=SETTING_PIPFILELOCK_SECTIONS))
    conf['pipfilelock_sections'] = json.loads(SETTING_PIPFILELOCK_SECTIONS)

    return conf


def which_pip(search_directory):

    # TODO also allow manual override from settings/env

    to_try = [".venv", "env", ".env"]

    try:
        pipenv_venv = check_output(["pipenv", "--venv"], cwd=(search_directory if search_directory else None))
        to_try.append(pipenv_venv.strip())
    except CalledProcessError:
        pass

    for t in to_try:
        pip_path = os.path.join(search_directory, t, "bin", "pip")
        if os.path.exists(pip_path):
            return pip_path

    return "pip"
