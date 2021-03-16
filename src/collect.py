import json
import sys

from models import load_dependency_files


def collect(input_path, output_path):

    if input_path.endswith("Pipfile.lock"):
        print("Interpreting given `Pipfile.lock` path as `Pipfile`")
        input_path = input_path[:-5]
    elif input_path.endswith("poetry.lock"):
        print("Using pyproject.toml as manifest for poetry.lock")
        input_path = input_path[:-11] + "pyproject.toml"

    print("Collecting manifests from {}".format(input_path))
    manifests = load_dependency_files(
        input_path
    )  # potentially recursive collection exposed as list

    # Manifest Processing
    output = {"manifests": {}}
    lockfiles = []
    direct_deps = []
    for manifest in manifests:
        print("Collecting contents of {filename}".format(filename=manifest.filename))

        manifest_dependencies = manifest.get_dependencies()
        output["manifests"][manifest.filename] = manifest_dependencies

        # Add any lockfiles for this manifest for later processing
        if manifest.lockfile:
            lockfiles.append(manifest.lockfile)

        # Record direct dependencies
        direct_deps.extend(
            [dep for dep in manifest_dependencies["current"]["dependencies"].keys()]
        )

    # Lockfile Processing
    output["lockfiles"] = {}

    for lockfile in lockfiles:
        print("Collecting contents of {filename}".format(filename=lockfile.filename))

        current_fingerprint = lockfile.fingerprint()
        current_dependencies = lockfile.get_dependencies(
            direct_dependencies=direct_deps
        )
        output["lockfiles"][lockfile.filename] = {
            "current": {
                "fingerprint": current_fingerprint,
                "dependencies": current_dependencies,
            }
        }

        lockfile.update()  # use the native tools to update the lockfile

        if current_fingerprint != lockfile.fingerprint():
            output["lockfiles"][lockfile.filename]["updated"] = {
                "fingerprint": lockfile.fingerprint(),
                "dependencies": lockfile.get_dependencies(
                    direct_dependencies=direct_deps
                ),
            }

    with open(output_path, "w+") as f:
        json.dump(output, f)


if __name__ == "__main__":
    collect(sys.argv[1], sys.argv[2])
