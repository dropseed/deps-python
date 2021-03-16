import re
import json
import sys

from models import Manifest, LockFile


def act(input_path, output_path):
    with open(input_path, 'r') as f:
        data = json.load(f)

    for lockfile_path, lockfile_data in data.get('lockfiles', {}).items():

        lockfile = LockFile(lockfile_path)
        lockfile.native_update()

        # 1) Do the lockfile update
        #    Since lockfile can change frequently, you'll want to "collect" the
        #    exact update that you end up making, in case it changed slightly from
        #    the original update that it was asked to make.

        lockfile_data['updated']['dependencies'] = lockfile.dio_dependencies()
        lockfile_data['updated']['fingerprint'] = lockfile.fingerprint()

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
            # if re.match(r'^\d', version_to_update_to):
            #     version_to_update_to = '==' + version_to_update_to

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

    with open(output_path, "w+") as f:
        json.dump(data, f)


if __name__ == "__main__":
    act(sys.argv[1], sys.argv[2])
