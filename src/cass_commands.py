import os
import time
import serial
import fitdecode
import numpy as np
from pathlib import Path
import pandas as pd
import serial.tools.list_ports
import datetime
from matplotlib import pyplot as plt
import warnings
from src.firmware_structs import FIRMWARE_DTYPES, COLUMN_ORDERS
from typing import Optional, Union, Dict, List
import re

# TODO:
# - Add windows compatability (for get_serial_ports & establish_serial)


class CassCommands:
    def __init__(self):
        self._ser_data = None
        self._ser_command = None
        self.reset_buff_used = False

    # --- Properties ---

    @property
    def ser_data(self):
        if self._ser_data is None:
            self._establish_serial()
        if not self._ser_data.is_open:
            self._ser_data.open()
        return self._ser_data

    @ser_data.setter
    def ser_data(self, port_name):
        baud_rate = 9600
        ser = serial.Serial(port_name, baud_rate)
        if not ser.is_open:
            ser.open()
        ser.reset_input_buffer()
        ser.flush()
        self._ser_data = ser

    @property
    def ser_command(self):
        if self._ser_command is None:
            self._establish_serial()
        if not self._ser_command.is_open:
            self._ser_command.open()
        return self._ser_command

    @ser_command.setter
    def ser_command(self, port_name):
        baud_rate = 9600
        ser = serial.Serial(port_name, baud_rate)
        if not ser.is_open:
            ser.open()
        ser.reset_output_buffer()
        ser.flush()
        self._ser_command = ser

    # --- Public Instance Methods ---

    def get_serial_ports(self):
        ports = serial.tools.list_ports.comports()
        logger_ports = [port.device for port in ports if "usbmodem" in port.device]
        if len(logger_ports) != 2:
            print("No dual serial ports found!")
            return None
        else:
            return logger_ports

    def set_RTC_time(self):
        # Get current time
        current_time = datetime.datetime.now(datetime.timezone.utc)
        print("Current time: ", current_time)
        # Format time string
        time_string = current_time.strftime("%Y-%m-%d %H:%M:%S")
        print("Time string: ", time_string)
        # Add termination character
        time_string += "x"

        # Send command to set RTC time
        self.ser_command.write(b"e")

        # Send time string
        self.ser_data.write(time_string.encode("utf-8"))

        # Wait for confirmation and unix time
        unix_time = ""
        while True:
            char = self.ser_data.read(1).decode("utf-8")
            if char == "x":
                break
            unix_time += char

        self._close_serial()

        if unix_time:
            print(f"RTC time set successfully. Unix time: {unix_time}")
            return True
        else:
            print("Failed to set RTC time")
            return False

    def get_RTC_time(self):
        self._flush_all()

        self.ser_command.write(b"h")
        unix_time = ""
        while True:
            char = self.ser_data.read(1).decode("utf-8")
            if char == "x":
                break
            unix_time += char
        return unix_time

    def list_files(self):
        self._open_serial()
        self._flush_all()

        self.ser_command.write(b"l")  # list files

        result = b""
        while b"xxx" not in result:
            if self.ser_data.in_waiting > 0:
                result += self.ser_data.read(self.ser_data.in_waiting)
        result = result.decode("utf-8")

        # self._close_serial()
        return result.splitlines()[:-1]

    def list_file_sizes(self):
        self._open_serial()
        self._flush_all()

        files = self.list_files()
        num_files = len(files)

        self.ser_command.write(b"z")  # list file sizes

        my_file_sizes = []
        my_file_sizes = [
            int(self.ser_data.read_until(b"\n").decode("utf-8").strip(), 2)
            for i in range(num_files)
        ]

        return my_file_sizes

    def delete_all_files(self, prompt_user=False):
        if prompt_user:
            user_input = input("Are you sure you want to delete all files? (y/n): ")
            if user_input.lower() != "y":
                print("Operation cancelled by user.")
                return 0
        [self._delete_file(filename) for filename in self.list_files()]

        self._close_serial()

        if len(self.list_files()) == 0:
            return True
        else:
            warnings.warn("Warning: error deleting files.")
            return False

    def read_file(self, filename, file_size):
        filename_term = filename + "x"
        filename_term = bytes(filename_term, "utf-8")

        sd_buff_size = 5120
        num_buffs = file_size / sd_buff_size
        if file_size % sd_buff_size != 0:
            num_buffs = file_size // sd_buff_size  # skip last incomplete sd_buffer
        num_buffs = int(num_buffs)
        bytes_received = []

        self.ser_command.write(b"o")  # open target file
        self.ser_data.write(filename_term)

        sd_buff = bytes()  # empty byte array for current buffer
        sd_byte_idx = 0  # byte index in current buffer
        retry_loop = False
        i = 0  # current buffer index
        while i < num_buffs:
            # read each buffer
            self.ser_command.write(b"t")  # send command for Teensy to send buffer
            self.ser_command.flush()  # wait until command is sent
            time_in_buffer = time.monotonic()

            sd_byte_idx = 0
            retry_loop = False
            while sd_byte_idx < sd_buff_size:
                # read each byte in buffer
                num_read = min(  # number of bytes to read
                    int(self.ser_data.in_waiting),  # number of bytes in serial buffer
                    sd_buff_size - sd_byte_idx,  # number of bytes remaining in buffer
                )
                if num_read > 0:
                    bytesIn = self.ser_data.read(num_read)  # incoming buffer
                    sd_byte_idx += num_read
                    sd_buff += bytesIn
                    time_in_buffer = time.monotonic()
                elif num_read == 0 and (time.monotonic() - time_in_buffer > 0.1):
                    self.ser_data.reset_input_buffer()  # clear serial buffer before initiating reset
                    buff_success = self._reset_buff((i) * sd_buff_size, filename)
                    sd_buff = []
                    retry_loop = True
                    self.reset_buff_used = True

                    break

            if retry_loop:
                i -= 1

            i += 1
            bytes_received.extend(sd_buff)
            sd_buff = bytes()
            sd_byte_idx = 0

        # DEBUG
        expected_byte_number = num_buffs * sd_buff_size
        number_buffs_off = expected_byte_number - len(bytes_received)
        print(f"Number of bytes short = {number_buffs_off} ({filename})")

        self.ser_command.write(b"c")  # close target file
        self._close_serial()
        return bytes_received

    def bytes_to_file(
        self, my_bytes, filename, filepath="tmp_{}".format(int(time.time()))
    ):
        if not os.path.exists(filepath):
            os.mkdir(filepath)

        full_filepath = Path(filepath, filename)
        with open(full_filepath, "wb") as f:
            f.write(bytes(my_bytes))
        return filepath

    def download_all(self):
        my_filenames = self.list_files()
        my_file_sizes = self.list_file_sizes()
        if not len(my_filenames):
            return []
        dir_name = "tmp_{}".format(int(time.time()))

        filepaths = [
            self.bytes_to_file(self.read_file(filename, file_size), filename, dir_name)
            for filename, file_size in zip(my_filenames, my_file_sizes)
        ]

        self._flush_all()
        # write metadata
        fw_ver = self.get_fw_ver()
        device_id = self.get_device_ID()
        md_path = Path(dir_name, "metadata.txt")
        with open(md_path, "w") as meta_file:
            meta_file.write(f"Firmware Ver: {fw_ver}\n")
            meta_file.write(f"Device ID: {device_id}\n")

        return filepaths[-1]

    def put_device_ID(self, device_ID):
        self.ser_command.write(b"p")  # eeprom put
        device_ID_orig = device_ID
        device_ID += "x"
        print("device_ID to write = ", device_ID)
        self.ser_data.write(bytes(device_ID, "utf-8"))
        while self.ser_data.in_waiting < len(device_ID) - 1:
            pass

        check_device_ID = self.ser_data.read_all().decode("utf-8")
        print("Device ID is: ", check_device_ID)

        self._close_serial()
        if check_device_ID == device_ID_orig:
            return True
        else:
            return False

    def get_device_ID(self):
        self._flush_all()

        self.ser_command.write(b"g")
        device_ID = b""
        while b"x" not in device_ID:
            if self.ser_data.in_waiting > 0:
                device_ID += self.ser_data.read(self.ser_data.in_waiting)
        device_ID = device_ID.decode("utf-8")

        self._close_serial()

        return device_ID[:-1]

    def put_rtc_install_timestamp(self, unix_install=None):
        if unix_install is None:
            unix_install = int(time.time())
        self.ser_command.write(b"j")  # eeprom put UNIX timestamp

        unix_install_orig = str(unix_install)
        unix_install = unix_install_orig + "x"

        print("unix_RTC_batt install time to write = ", unix_install)
        self.ser_data.write(unix_install.encode("utf-8"))

        while self.ser_data.in_waiting < len(unix_install) - 1:
            pass

        check_unix_install = self.ser_data.read_all().decode("utf-8").strip("x\n\r ")
        print("Unix install is: ", check_unix_install)

        try:
            ts_int = int(check_unix_install)
            dt = datetime.datetime.fromtimestamp(ts_int)
            print("Datetime install is:", dt.strftime("%Y-%m-%d %H:%M:%S"))
        except ValueError:
            print("Error: could not parse timestamp")

        self._close_serial()
        return check_unix_install == unix_install_orig

    def get_rtc_install_timestamp(self):
        self._flush_all()
        self._open_serial()

        self.ser_command.write(b"i")
        rtc_install = b""
        while b"x" not in rtc_install:
            if self.ser_data.in_waiting > 0:
                rtc_install += self.ser_data.read(self.ser_data.in_waiting)
        rtc_install = rtc_install.decode("utf-8")
        rtc_install = rtc_install[:-1]
        self._close_serial()

        dt = datetime.datetime.fromtimestamp(int(rtc_install))
        print("Datetime install is:", dt.strftime("%Y-%m-%d %H:%M:%S"))

        return rtc_install

    def get_fw_ver(self):
        self._flush_all()

        self.ser_command.write(b"a")
        fw_ver = b""
        while b"x" not in fw_ver:
            if self.ser_data.in_waiting > 0:
                fw_ver += self.ser_data.read(self.ser_data.in_waiting)
        fw_ver = fw_ver.decode("utf-8")
        self._close_serial()
        return fw_ver[:-1]

    # --- Static and Class Methods

    @classmethod
    def process_data_file(cls, filepath: str, filename: str, fw_ver="std"):
        full_filename = Path(filepath) / filename

        # Match firmware type based on substrings
        if "i2c_2" in fw_ver:
            dtype_key = "i2c_2"
        elif "i2c_1" in fw_ver:
            dtype_key = "i2c_1"
        else:
            dtype_key = "std"

        try:
            dt = FIRMWARE_DTYPES[dtype_key]()
            column_order = COLUMN_ORDERS[dtype_key]
        except KeyError:
            raise ValueError(f"Unsupported firmware version: {fw_ver}")

        data = np.fromfile(full_filename, dtype=dt)
        df = pd.DataFrame(data)

        if (df["tmicros"] < 0).any():
            df["tmicros"] = df["tmicros"].astype(np.float64)
            df["tmicros"] = cls.handle_tmicros_rollover(df["tmicros"])

        df["tmicros"] -= df["tmicros"].iloc[0]
        df.insert(1, "t", df["tmicros"] * 1e-6)

        # Only reorder columns that exist in this firmware's dtype
        df = df[[col for col in column_order if col in df.columns]]

        return df

    @staticmethod
    def find_and_parse_metadata(
        dir_path: str,
        filename: str = "metadata.txt",
        recursive: bool = True,
        first_only: bool = True,
    ) -> Union[Dict[str, Optional[str]], List[Dict[str, Optional[str]]], None]:
        """
        Search for metadata files and parse them.
        - If no file is found returns None.
        - If first_only=True returns a single parsed dict for the first match.
        - If first_only=False returns a list of parsed dicts (one per found file).
        """
        files = CassCommands._find_metadata_files(
            dir_path, filename=filename, recursive=recursive
        )
        if not files:
            return None

        parsed = []
        for f in files:
            try:
                parsed.append(CassCommands._parse_metadata_file(str(f)))
            except Exception as exc:
                # skip files that fail to read/parse; optionally log the error
                parsed.append({"error": f"failed to parse {f}: {exc}"})

        if first_only:
            return parsed[0]
        return parsed

    @staticmethod
    def handle_tmicros_rollover(col):
        step_size = col[1] - col[0]
        new_col = np.arange(0, len(col) * step_size, step_size, dtype=np.int64)
        return new_col

    @staticmethod
    def process_fit_file(filepath, filename):
        my_path = str(Path(filepath, filename))
        df_record = pd.DataFrame()
        df_session = pd.DataFrame()
        with fitdecode.FitReader(my_path) as fit:
            for frame in fit:
                if frame.frame_type == fitdecode.FIT_FRAME_DATA:
                    if frame.name == "record":
                        frame_data = {field.name: field.value for field in frame.fields}
                        frame_df = pd.DataFrame([frame_data])
                        df_record = pd.concat([df_record, frame_df], ignore_index=True)
                    elif frame.name == "session":
                        frame_data = {field.name: field.value for field in frame.fields}
                        frame_df = pd.DataFrame([frame_data])
                        df_session = pd.concat(
                            [df_session, frame_df], ignore_index=True
                        )
        return df_session, df_record

    # --- Private Methods ---

    def _establish_serial(self, baud_rate=9600):
        serial_ports = self.get_serial_ports()
        if serial_ports is None:
            raise ValueError(
                "No logger detected, makes sure it's plugged in and powered on!"
            )
        ser_data = serial.Serial(serial_ports[0], baud_rate)
        ser_command = serial.Serial(serial_ports[1], baud_rate)
        if not ser_data.is_open:
            ser_data.open()
        if not ser_command.is_open:
            ser_command.open()

        ser_data.reset_input_buffer()
        ser_command.reset_output_buffer()

        self._flush_ser_port(ser_data)
        self._flush_ser_port(ser_command)

        ser_command.write(b"u")
        ser_data.write(b"u")

        timer = time.monotonic()
        while ser_data.in_waiting < 1 and ser_command.in_waiting < 1:
            if time.monotonic() - timer > 3:
                raise TimeoutError("Timeout waiting for serial response from device.")

        data_response = ser_data.read(ser_data.in_waiting).decode("utf-8")
        command_response = ser_command.read(ser_command.in_waiting).decode("utf-8")

        if command_response == "x":
            ser_data, ser_command = ser_command, ser_data
        elif data_response == "x":
            pass
        else:
            raise RuntimeError("ERROR! No response from teensy!")

        self._flush_ser_port(ser_data)
        self._flush_ser_port(ser_command)

        self._ser_data = ser_data
        self._ser_command = ser_command

    def _flush_ser_port(self, ser_obj):
        # Flush output buffer and clear input buffer of the given serial object
        ser_obj.reset_input_buffer()
        ser_obj.flush()

    def _flush_all(self):
        self._flush_ser_port(self.ser_data)
        self._flush_ser_port(self.ser_command)

    def _reset_buff(self, reset_pos, filename):
        START_MARKER = b"\xff\xfe\xfd"
        END_MARKER = b"\xfd\xfe\xff"

        print(f"IN RESET BUFF, file: {filename} at pos: {reset_pos}")

        self.ser_command.write(b"n")  # send reset buffer command
        self._flush_ser_port(self.ser_command)  # wait until command is sent
        # self.ser_command.flush()

        time.sleep(0.05)  # NOTE: not sure if needed

        reset_pos = START_MARKER + str(reset_pos).encode("utf-8") + END_MARKER
        self.ser_data.write(reset_pos)  # send reset idx
        self._flush_ser_port(self.ser_data)  # wait until idx is sent
        # self.ser_data.flush()

        # Validate that the correct position was set
        self.ser_data.read_until(START_MARKER)
        return_position = self.ser_data.read_until(END_MARKER)
        return_position = return_position[: -len(END_MARKER)]
        try:
            return_position = return_position.decode("utf-8")
        except UnicodeDecodeError:
            print("Error decoding return position from device.")
        print(return_position)

        # Make sure there isn't any leftover data in the serial buffers
        # self.ser_data.reset_input_buffer()
        while self.ser_data.in_waiting > 0:
            self.ser_data.read(self.ser_data.in_waiting)
            print("Clearing serial buffer after...")
        self._flush_all()
        return True

    def _delete_file(self, filename):
        self.ser_command.reset_input_buffer()  # TODO: should this be a normal flush?
        self.ser_command.write(b"x")  # delete file

        filename = bytes(filename, "utf-8")  # write filename to be deleted
        self.ser_command.write(filename)

        b_success = self.ser_data.read_until(b"x")  # check for success
        b_success = int(b_success.decode("ascii").strip("x"))
        if b_success:
            return True
        else:
            warnings.warn("Warning: error deleting file.")
            return False

    def _close_serial(self):
        self.ser_data.close()
        self.ser_command.close()

    def _open_serial(self):
        if not self.ser_data.is_open:
            self.ser_data.open()
        if not self.ser_command.is_open:
            self.ser_command.open()

    @staticmethod
    def _find_metadata_files(
        dir_path: str, filename: str = "metadata.txt", recursive: bool = True
    ) -> List[Path]:
        """
        Return a list of Path objects for files named `filename` inside dir_path.
        - filename match is case-insensitive.
        - If recursive=True, searches subdirectories (rglob); otherwise only top-level (iterdir).
        """
        root = Path(dir_path)
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        name_lower = filename.lower()
        matches: List[Path] = []
        try:
            if recursive:
                for p in root.rglob("*"):
                    if p.is_file() and p.name.lower() == name_lower:
                        matches.append(p)
            else:
                for p in root.iterdir():
                    if p.is_file() and p.name.lower() == name_lower:
                        matches.append(p)
        except PermissionError:
            # optionally handle permission errors (skip folders you can't access)
            pass

        return matches

    @staticmethod
    def _parse_metadata_file(path: str) -> Dict[str, Optional[str]]:
        """Read a metadata file and parse it."""
        txt = Path(path).read_text(encoding="utf-8")
        fw_match = re.search(
            r"Firmware\s*(?:Ver(?:\.|sion)?)\s*[:=]\s*([^\r\n]+)", txt, re.I
        )
        id_match = re.search(r"Device\s*ID\s*[:=]\s*([^\r\n]+)", txt, re.I)

        def _clean(s: Optional[str]) -> Optional[str]:
            if s is None:
                return None
            s = s.strip()
            # remove surrounding quotes if any
            if (s.startswith('"') and s.endswith('"')) or (
                s.startswith("'") and s.endswith("'")
            ):
                s = s[1:-1].strip()
            return s

        return {
            "firmware_version": _clean(fw_match.group(1)) if fw_match else None,
            "device_id": _clean(id_match.group(1)) if id_match else None,
        }
