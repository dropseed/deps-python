import tempfile
import json


def write_json_to_temp_file(data):
    """Writes JSON data to a temporary file and returns the path to it"""
    fp = tempfile.NamedTemporaryFile(delete=False)
    fp.write(json.dumps(data).encode('utf-8'))
    fp.close()
    return fp.name
