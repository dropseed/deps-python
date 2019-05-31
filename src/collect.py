import json
import sys

from models import Manifest
from utils import write_json_to_temp_file


def collect(input_path, output_path):

    print('Collecting manifests from {}'.format(input_path))
    manifests = Manifest.collect_manifests(input_path)  # potentially recursive collection exposed as list

    # Manifest Processing
    output = {
        'manifests': {}
    }
    lockfiles = []
    direct_deps = []
    for manifest in manifests:
        print('Collecting contents of {filename}'.format(filename=manifest.filename))

        output['manifests'][manifest.filename] = manifest.dio_dependencies()

        # Add any lockfiles for this manifest for later processing
        if manifest.lockfile:
            lockfiles.append(manifest.lockfile)

        # Record direct dependencies
        direct_deps.extend([dep.key for dep in manifest.dependencies()])

    # Lockfile Processing
    output["lockfiles"] = {}

    for lockfile in lockfiles:
        print('Collecting contents of {filename}'.format(filename=lockfile.filename))

        current_fingerprint = lockfile.fingerprint()
        current_dependencies = lockfile.dio_dependencies(direct_dependencies=direct_deps)
        output['lockfiles'][lockfile.filename] = { 'current': {
                                                                'fingerprint': current_fingerprint,
                                                                'dependencies': current_dependencies,
                                                                }
                                                            }

        lockfile.native_update()  # use the native tools to update the lockfile

        if current_fingerprint != lockfile.fingerprint():
            output['lockfiles'][lockfile.filename]['updated'] = {
                'fingerprint': lockfile.fingerprint(),
                'dependencies': lockfile.dio_dependencies(direct_dependencies=direct_deps),
            }

    with open(output_path, "w+") as f:
        json.dump(output, f)


if __name__ == "__main__":
    collect(sys.argv[1], sys.argv[2])
