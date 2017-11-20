"""Scan local folders for firmwares"""
import logging
import os
import re
import zipfile
import hashlib
import json

REGEX_HOMIE = re.compile(
    b"\x25\x48\x4f\x4d\x49\x45\x5f\x45\x53\x50\x38\x32\x36\x36\x5f\x46\x57\x25")
REGEX_NAME = re.compile(b"\xbf\x84\xe4\x13\x54(.+)\x93\x44\x6b\xa7\x75")
REGEX_VERSION = re.compile(b"\x6a\x3f\x3e\x0e\xe1(.+)\xb0\x30\x48\xd4\x1a")
REGEX_BRAND = re.compile(b"\xfb\x2a\xf5\x68\xc0(.+)\x6e\x2f\x0f\xeb\x2d")

REGEX_PYTHON_VERSION = r"^__version__ = ['\"]([^'\"]*)['\"]"
REGEX_PYTHON_DESC = r"^\"\"\"([^(?:\"\"\")]*)\"\"\""

def sizeof_fmt(num, suffix="B"):
    """Format file size in a human readable way"""
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Y", suffix)


BUFFER_SIZE = 4096


def file_md5(path):
    """Calculate MD5 hash for a given file"""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(BUFFER_SIZE), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def scan_esp_firmware(path, fw_file, db):
    """Detect ESP compatible firmwares"""
    logging.debug("Scanning arduino compatible firmware %s", fw_file)
    db["type"] = "esp8266"

    with open(os.path.join(path, fw_file), "rb") as firmware_file:
        firmware_binary = firmware_file.read()
        regex_name_result = REGEX_NAME.search(firmware_binary)
        regex_version_result = REGEX_VERSION.search(firmware_binary)
        regex_brand_result = REGEX_BRAND.search(firmware_binary)
        if regex_name_result:
            db["name"] = regex_name_result.group(1).decode()
        if regex_version_result:
            db["version"] = regex_version_result.group(1).decode()
        if regex_brand_result:
            db["brand"] = regex_brand_result.group(1).decode()

    fw_file_name = os.path.splitext(fw_file)[0]
    fw_desc_path = os.path.join(path, "%s.txt" % fw_file_name)
    if os.path.isfile(fw_desc_path):
        with open(fw_desc_path, "r") as desc:
            db["description"] = desc.read()


def scan_bundle_firmware(path, fw_file, db):
    """Scan desktop bundle compatible firmwares (python, javascript)"""
    logging.debug("Scanning bundle compatible firmware %s", fw_file)
    fw_path = os.path.join(path, fw_file)
    if not zipfile.is_zipfile(fw_path):
        logging.error("Invalid bundle zip file %s, skipping", fw_file)
        return
    with zipfile.ZipFile(fw_path, "r") as bundle:
        try:
            bundle.getinfo("main.py")
            # version detection
            main_as_text = bundle.read("main.py");
            version_result = re.search(REGEX_PYTHON_VERSION, main_as_text, re.M)
            if version_result:
                db["version"] = version_result.group(1)

            # description extraction
            description_result = re.search(REGEX_PYTHON_DESC, main_as_text, re.M)
            if description_result:
                db["description"] = description_result.group(1)
        except Exception:
            pass
        else:
            db["type"] = "python"

        try:
            bundle.getinfo("package.json")
            package = json.loads(bundle.read('package.json'))
            db["description"] = package["description"]
            db["version"] = package["version"]
        except Exception:
            pass
        else:
            db["type"] = "javascript"


def scan_firmwares(path, db):
    """Scan local firmware files"""
    fw_types = {".bin": scan_esp_firmware,
                ".zip": scan_bundle_firmware
                }

    for fw_file in os.listdir(path):
        fw_path = os.path.join(path, fw_file)
        if not os.path.isfile(fw_path):
            continue

        fw_file_name, fw_file_ext = os.path.splitext(fw_file)
        if fw_file_ext not in [".bin", ".zip"]:
            continue

        regex = re.compile(r"(.*)\-(\d+\.\d+\.\d+)")
        regex_result = regex.search(fw_file_name)

        if not regex_result:
            logging.debug(
                "Could not parse firmware details from %s, skipping", fw_file)
            continue

        firmware_info = db[fw_file] = {}

        firmware_info["filename"] = fw_file

        fw_types[fw_file_ext](path, fw_file, firmware_info)

        if "name" not in firmware_info:
            firmware_info["name"] = regex_result.group(1)
        firmware_info["filename_version"] = regex_result.group(2)

        stat = os.stat(fw_path)
        firmware_info["human_size"] = sizeof_fmt(stat.st_size)
        firmware_info["checksum"] = file_md5(fw_path)
