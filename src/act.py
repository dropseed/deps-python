import re
import json

from models import Manifest, LockFile
from utils import write_json_to_temp_file, run


def act():
    with open('/dependencies/input_data.json', 'r') as f:
        data = json.load(f)

    # create a new branch for this update
    run('deps branch')

    for lockfile_path, lockfile_data in data.get('lockfiles', {}).items():
        # If "lockfiles" are present then it means that there are updates to
        # those lockfiles that you can make. The most basic way to handle this
        # is to use whatever "update" command is provided by the package
        # manager, and then commit and push the entire update. You can try to be
        # more granular than that if you want, but performing the entire "update"
        # at once is an easier place to start.

        # Granular, package by package upgrades
        # for dep_name, dep_data in lockfile_data['updated']['dependencies'].items():
        #     lockfile = LockFile(lockfile_path)
        #     dep_version = dep_data['installed']['name']
        #
        #     # Prefix the version with "==" automatically if it (shouldn't) have it
        #     if re.match('^\d', dep_version):
        #         dep_version = '==' + dep_version
        #     run(['pipenv', 'install', '{dep_name}{dep_version}'.format(dep_name=dep_name, dep_version=dep_version)])
        #     dep_name_ver = '{dep_name}{dep_version}'.format(dep_name=dep_name, dep_version=dep_version)
        #     lockfile.native_update(dep_name_ver)

        # # All at once
        lockfile = LockFile(lockfile_path)
        lockfile.native_update()

        # 1) Do the lockfile update
        #    Since lockfile can change frequently, you'll want to "collect" the
        #    exact update that you end up making, in case it changed slightly from
        #    the original update that it was asked to make.

        lockfile_data['updated']['dependencies'] = lockfile.dio_dependencies()
        lockfile_data['updated']['fingerprint'] = lockfile.fingerprint()

        # 2) Add and commit the changes
        run('deps commit -m "Update {}" {}'.format(lockfile_path, lockfile_path))

    for manifest_path, manifest_data in data.get('manifests', {}).items():
        for dependency_name, updated_dependency_data in manifest_data['updated']['dependencies'].items():
            manifest = Manifest(manifest_path)
            print('~'*80 + '\n')
            print(manifest.content)
            print('='*80 + '\n')
            installed = manifest_data['current']['dependencies'][dependency_name]['constraint']
            version_to_update_to = updated_dependency_data['constraint']

            # automatically prefix it with == if it looks like it is an exact version
            # and wasn't prefixed already
            if re.match(r'^\d', version_to_update_to):
                version_to_update_to = '==' + version_to_update_to

            dependency = [x for x in manifest.dependencies() if x.key == dependency_name][0]
            updated_content = manifest.updater(
                content=manifest.content,
                dependency=dependency,
                version=version_to_update_to,
                spec='',  # we'll have spec included in "version"
            )
            print(updated_content)
            print('-'*80 + '\n')

            with open(manifest_path, 'w+') as f:
                f.write(updated_content)

            run('deps commit -m "Update {} from {} to {}" {}'.format(dependency_name, installed, updated_dependency_data['constraint'], manifest_path))

    run('deps pullrequest {}'.format(write_json_to_temp_file(data)))
