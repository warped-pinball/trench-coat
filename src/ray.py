import base64
import hashlib
import json
import os
import time

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005
COMMAND_CHUNK_SIZE = 5000


class Ray:
    _instances = set()

    def __init__(self, port: str):
        # Track this instance
        Ray._instances.add(self)

        self.port = port
        self.open()

    def __del__(self):
        # Clean up when the instance is garbage-collected
        self.close()

    def close(self):
        """Properly close the serial connection"""
        if hasattr(self, "ser") and self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass  # Already closed or error closing
        # Remove from tracked instances
        if self in Ray._instances:
            Ray._instances.remove(self)

    @classmethod
    def close_all(cls):
        """Close all Ray instances"""
        for ray in list(cls._instances):
            ray.close()

    def open(self):
        """Open the serial connection"""
        if not hasattr(self, "ser") or not self.ser or not self.ser.is_open:
            self.ser = serial.Serial(self.port, 115200, timeout=0.1)
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(b"\x03\x03")  # Ctrl+C
            time.sleep(0.1)  # Give time for the interrupt to process
            self.ser.write(b"\x01")
            time.sleep(0.1)  # Give time for the interrupt to process

    @classmethod
    def find_board_ports(cls) -> list[str]:
        board_ports = []
        for port_info in serial.tools.list_ports.comports():
            if port_info.vid == PICO_VID and port_info.pid == PICO_PID:
                board_ports.append(port_info.device)
        return board_ports

    def send_command(self, script, ignore_response=False) -> str:
        """
        Send a script to the MicroPython board in *raw REPL mode*,
        capture and return stdout (combined into one string),
        or raise an exception if there's error output.

        For multi-line scripts, ensure the script is properly
        spaced / indented as needed. We'll send it as-is in raw mode.
        """
        # Make sure the serial port is open
        self.open()

        if isinstance(script, list):
            script = "\n".join(script)

        if not script.endswith("\n"):
            script += "\n"  # Ensure it ends with a newline

        if not ignore_response:
            # flush the output buffer
            self.ser.flushOutput()
            # flush the input buffer
            self.ser.flushInput()

        self.ser.write(script.encode("utf-8"))

        # 3) Send Ctrl-D to indicate we're done and want to execute
        self.ser.write(b"\x04")

        if ignore_response:
            return

        # read in the initial "OK" response
        buf = b""
        while True:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting)
                if b"OK" in chunk:
                    # add anything after the OK to the buffer
                    buf += chunk[chunk.index(b"OK") + 2 :]
                    break
            time.sleep(0.01)

        # wait until we have data in the input buffer
        while self.ser.in_waiting == 0:
            time.sleep(0.01)

        # read all until it's been idle for 1 second
        start_time = time.time()
        while True:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting)
                buf += chunk
                start_time = time.time()
            else:
                if time.time() - start_time > 1.0:
                    break
            time.sleep(0.01)

        # encode and return the output
        buf = buf.decode("utf-8", errors="replace")
        return buf

    def write_update_to_board(self, update_files: list[dict[str, str]]):
        """
        Example of how we might combine the raw REPL method with chunked upload.
        Note that if you're sending large base64 data, you might prefer
        a different chunking approach or partial reads/writes.
        """

        def generate_transfer_script(files: list[dict[str, str]]):
            setup_lines = [
                "import os",
                "import binascii",
                "import hashlib",
                "f = None",
                "hash_checks = []",
                "def w(data):",
                "    global f",
                "    f.write(binascii.a2b_base64(data))",
                "    f.flush()",
                "",
                "def hash_check(path, expected_hash):",
                "    try:",
                "        sha256 = hashlib.sha256()",
                "        with open(path, 'rb') as f:",
                "            while True:",
                "                chunk = f.read(1024)",
                "                if not chunk:",
                "                    break",
                "                sha256.update(chunk)",
                "        hash = binascii.hexlify(sha256.digest()).decode('utf-8')",
                "    except Exception:",
                "        hash = ''",
                "    global hash_checks",
                "    hash_checks.append((path, hash == expected_hash))",
                "",
                "def mdir(path):",
                "    try:",
                "        os.mkdir(path)",
                "    except OSError:",
                "        pass",
                "",
                "def execute_file(path):",
                "    module_path = path.replace('/', '.').replace('.py', '')",
                "    if module_path.startswith('.'):",
                "        module_path = module_path[1:]",
                "    try:",
                "        imported_module = __import__(module_path)",
                "        if hasattr(imported_module, 'main'):",
                "            imported_module.main()",
                "    except Exception as e:",
                "        print('Error message:', str(e))",
                "        print('Error executing file:', path)",
                "    try:" "        os.remove(path)",
                "    except OSError:",
                "        pass",  # file probably removed itself
            ]

            yield "\n".join(setup_lines)

            for i, file_info in enumerate(files):
                # Print progress
                print(f"Uploading file {i + 1} of {len(files)}: {file_info['filename']}" + " " * 20, end="\r")

                filename = file_info["filename"]
                file_metadata = file_info["metadata"]
                file_contents = file_info["base64_contents"]

                if not filename:
                    raise ValueError(f"Missing filename in {file_info}")

                # For consistency, we always use a leading slash
                if not filename.startswith("/"):
                    filename = "/" + filename

                dir_path = os.path.dirname(filename)
                if dir_path not in ["", "/"]:
                    yield f"mdir('{dir_path}')"

                yield f"f = open('{filename}', 'wb')"

                # Process base64 data in chunks
                chunk_size = COMMAND_CHUNK_SIZE - 20
                for i in range(0, len(file_contents), chunk_size):
                    chunk = file_contents[i : i + chunk_size]
                    yield f"w('{chunk}')"

                yield "f.close()"

                # calculate the checksum based on the file contents
                hasher = hashlib.sha256()
                decoded_contents = base64.b64decode(file_contents)
                hasher.update(decoded_contents)
                expected_hash = hasher.hexdigest()

                yield f"hash_check('{filename}', '{expected_hash}')"
                # If the file is marked as executable, run it
                if file_metadata.get("execute", False):
                    yield f"execute_file('{filename}')"

        # figure out what files need to be updated
        required_files = self.get_files_to_update(update_files)

        # Generate the script lines in a generator
        script_lines = generate_transfer_script([file_info for file_info in update_files if file_info["filename"] in required_files or file_info["metadata"].get("execute", False)])
        current_block = []
        current_len = 0

        # Iterate over the script lines and send them in chunks
        for i, line in enumerate(script_lines):
            if current_len + len(line) > COMMAND_CHUNK_SIZE:
                # send the block
                block_script = "\n".join(current_block)
                self.send_command(block_script, ignore_response=True)
                current_block = [line]
                current_len = len(line)
            else:
                current_block.append(line)
                current_len += len(line)

        # Send any remainder
        if current_block:
            block_script = "\n".join(current_block)
            self.send_command(block_script, ignore_response=True)

        print()

        output = self.send_command("print([check for check in hash_checks if not check[1]])", ignore_response=False)

        # find first [
        start = output.find("[")
        # find last ]
        end = output.rfind("]")
        if start == -1 or end == -1:
            raise ValueError(f"Board failed to return hash checks: {output}")
        # remove anything before first [ or after last ]
        output = output[start : end + 1].strip()
        if output == "[]":
            print("All files uploaded successfully.")
            return

        raise ValueError(f"Board failed to upload files: {output}")

    def enter_bootloader_mode(self):
        """
        Reset the board into the UF2 bootloader (might need physically to reset on some boards).
        """
        self.send_command("import machine\nmachine.bootloader()", ignore_response=True)

    def wipe_board(self):
        """
        Remove all files and directories on the board's filesystem.
        """
        script = [
            "import os",
            "def remove(path):",
            "    try:",
            "        os.remove(path)",
            "    except OSError:",
            "        for entry in os.listdir(path):",
            "            remove(path + '/' + entry)",
            "        os.rmdir(path)",
            "",
            "for entry in os.listdir('/'):",
            "    remove('/' + entry)",
        ]
        self.send_command(script)

    def restart_board(self):
        """
        Soft reset the board. This causes a reboot, so the serial connection might
        disconnect or the REPL might get re-initialized.
        """
        self.send_command("import machine\nmachine.reset()", ignore_response=True)

    def sha256_index(self) -> dict[str, str]:
        """
        Get the SHA256 of every file on the board as a dict.
        We run code that collects file : digest in JSON, then parse locally.
        Recursively walks through all directories.
        """
        script_lines = [
            "import os",
            "import hashlib",
            "import json",
            "import binascii",
            "",
            "files = {}",
            "",
            "def process_directory(path):",
            "    try:",
            "        for entry in os.listdir(path):",
            "            full_path = path + '/' + entry if path != '/' else '/' + entry",
            "            try:",
            "                # Check if entry is a directory",
            "                is_dir = os.stat(full_path)[0] & 0x4000",
            "                if is_dir:",
            "                    process_directory(full_path)  # Recurse into directory",
            "                else:",
            "                    # Calculate hash for file",
            "                    sha256 = hashlib.sha256()",
            "                    with open(full_path, 'rb') as f:",
            "                        while True:",
            "                            chunk = f.read(1024)",
            "                            if not chunk:",
            "                                break",
            "                            sha256.update(chunk)",
            "                    files[full_path] = binascii.hexlify(sha256.digest()).decode('utf-8')",
            "            except Exception as e:",
            "                files[full_path] = f'Error: {str(e)}'",
            "    except Exception as e:",
            "        files[path] = f'Error listing directory: {str(e)}'",
            "",
            "# Start recursive processing from root",
            "process_directory('/')",
            "",
            "print(json.dumps(files))",
        ]
        output = self.send_command(script_lines)

        # remove anything before first { or after last }
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"Board returned invalid JSON for file hashes: {output}")

        output = output[start : end + 1].strip()

        if len(output) == 0:
            return {}

        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            raise ValueError(f"Board returned invalid JSON for file hashes: {output}") from e

    def get_files_to_update(self, expected_files: list[dict[str, str]]) -> list[str]:
        required_files = []

        expected_sha256_index = {}
        for file_info in expected_files:
            # add / to the start of the filename if it doesn't exist
            if not file_info["filename"].startswith("/"):
                file_info["filename"] = "/" + file_info["filename"]

            hasher = hashlib.sha256()
            # decode the base64 contents to bytes
            decoded_contents = base64.b64decode(file_info["base64_contents"])
            hasher.update(decoded_contents)
            if file_info["filename"] in expected_sha256_index:
                # If the file already exists, check if the hashes match
                # This could happen for files that the update modifies or
                # if a filename gets reused by executeable files
                if expected_sha256_index[file_info["filename"]] != hasher.hexdigest():
                    required_files.append(file_info["filename"])
                    # remove the file from the expected list, we don't need to check this again
                    del expected_sha256_index[file_info["filename"]]
            else:
                expected_sha256_index[file_info["filename"]] = hasher.hexdigest()

        # Get the SHA256 index from the board
        sha256_index = self.sha256_index()

        for file in expected_sha256_index.keys():
            if file not in sha256_index:
                required_files.append(file)
            elif sha256_index[file] != expected_sha256_index[file]:
                required_files.append(file)

        return required_files
