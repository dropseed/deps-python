import re
import json
import sys

from models import load_dependency_file


def act(input_path, output_path):
    with open(input_path, "r") as f:
        data = json.load(f)

    for lockfile_path, lockfile_data in data.get("lockfiles", {}).items():
        lockfile = load_dependency_file(lockfile_path)
        lockfile.update()

        lockfile_data["updated"]["dependencies"] = lockfile.get_dependencies()
        lockfile_data["updated"]["fingerprint"] = lockfile.fingerprint()

    for manifest_path, manifest_data in data.get("manifests", {}).items():
        for dependency_name, updated_dependency_data in manifest_data["updated"][
            "dependencies"
        ].items():
            manifest = load_dependency_file(manifest_path)
            manifest.update_dependency(
                dependency=dependency_name,
                constraint=updated_dependency_data["constraint"],
            )

    with open(output_path, "w+") as f:
        json.dump(data, f)


if __name__ == "__main__":
    act(sys.argv[1], sys.argv[2])
