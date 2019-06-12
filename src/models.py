import hashlib
import os
import pip._internal
import json
from subprocess import check_call

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

        self.conf = get_config_settings()

    def _parse(self):
        with open(self.filename, 'r') as f:
            self.content = f.read()

        self.parser = dparse.parse(content=self.content, path=self.filename)

        if not self.parser.is_valid:
            raise Exception('Unable to parse {filename}'.format(filename=self.filename))

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

            output["current"]["dependencies"][dep.key] = {
                'source': dep.source,
                'constraint': str(dep.specs) or "*",
            }

            available = get_available_versions_for_dependency(dep.key, dep.specs)
            if available:
                output["updated"]["dependencies"][dep.key] = {
                    'source': dep.source,
                    'constraint': '==' + available[-1],
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


def get_available_versions_for_dependency(name, specs):
    # This uses the native pip library to do the package resolution
    # TODO figure out how to do this without mocking all these useless things...
    list_command = pip._internal.commands.ListCommand()
    pip_args = json.loads(os.getenv("DEPS_SETTING_PIP_ARGS", "[]"))
    options, args = list_command.parse_args(pip_args)

    warn_on_missing_versions = json.loads(os.getenv("DEPS_SETTING_WARN_ON_MISSING_VERSIONS", "false"))

    with list_command._build_session(options) as session:
        index_urls = [options.index_url] + options.extra_index_urls
        if options.no_index:
            index_urls = []

        finder = list_command._build_package_finder(options, index_urls, session)

        all_candidates = list(finder.find_all_candidates(name))
        all_versions = set([str(c.version) for c in all_candidates])

        filtered_candidate_versions = list(specs.filter(all_versions))
        filtered_candidates = [c for c in all_candidates if str(c.version) in filtered_candidate_versions]

        if not filtered_candidates:
            msg = "No versions found for {} matching spec {}".format(name, specs)
            if warn_on_missing_versions:
                print("Warning: {}".format(msg))
                return []
            else:
                raise Exception(msg)

        # this is the highest version in the specified range, everything above this is outside our constraints
        best_candidate = finder.candidate_evaluator.get_best_candidate(filtered_candidates)

    newer_versions = [c.version for c in all_candidates if c.version > best_candidate.version]
    in_order = sorted(set(newer_versions))

    return [str(x) for x in in_order]


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
