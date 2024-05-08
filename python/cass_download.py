import os
import time
import serial
import numpy as np
from pathlib import Path
import pandas as pd
import serial.tools.list_ports

# Copyright (c) 2023 Cass Labs LLC (author: Matthew Morrison)

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# -------------------------------------------------------------------------- #

# TODO: Windows compatability
# TODO: manual port setting


def get_serial_ports():
    ports = serial.tools.list_ports.comports()
    logger_ports = [port.device for port in ports if "usbmodem" in port.device]
    if len(logger_ports) != 2:
        print("Error! Dual Serial Ports not found!")
        return None
    else:
        return logger_ports


def establish_serial(baud_rate=9600):
    serial_ports = get_serial_ports()
    ser_data = serial.Serial(serial_ports[0], baud_rate)
    ser_command = serial.Serial(serial_ports[1], baud_rate)
    if not ser_data.is_open:
        ser_data.open()
    if not ser_command.is_open:
        ser_command.open()

    ser_data.reset_input_buffer()
    ser_command.reset_output_buffer()

    _flush_all(ser_data, ser_command)

    ser_command.write(b"u")
    ser_data.write(b"u")

    while ser_data.in_waiting < 1 and ser_command.in_waiting < 1:
        pass

    data_response = ser_data.read(ser_data.in_waiting).decode("utf-8")
    command_response = ser_command.read(ser_command.in_waiting).decode("utf-8")

    if command_response == "x":
        ser_data, ser_command = ser_command, ser_data
    elif data_response == "x":
        pass
    else:
        print("No response from teensy!")
        return None

    _flush_all(ser_data, ser_command)
    return ser_data, ser_command


def _flush_all(ser_data, ser_command):
    ser_data.flushInput()
    ser_data.flush()
    ser_command.flushInput()
    ser_command.flush()


def list_files():
    ser_data, ser_command = establish_serial()
    ser_command.write(b"l")  # list files

    result = b""
    while b"xxx" not in result:
        if ser_data.in_waiting > 0:
            result += ser_data.read(ser_data.in_waiting)
    result = result.decode("utf-8")

    _close_serial(ser_data, ser_command)

    return result.splitlines()[:-1]


def file_sizes():
    ser_data, ser_command = establish_serial()

    files = list_files()  # list files
    num_files = len(files)

    ser_command.write(b"z")  # list file sizes

    my_file_sizes = []
    my_file_sizes = [
        int(ser_data.read_until(b"\n").decode("utf-8").strip(), 2)
        for i in range(num_files)
    ]

    _close_serial(ser_data, ser_command)

    return my_file_sizes


def delete_all_files():
    ser_data, ser_command = establish_serial()

    [_delete_file(filename, ser_data, ser_command) for filename in list_files()]

    _close_serial(ser_data, ser_command)

    if len(list_files()) == 0:
        return 1
    else:
        print("Error deleting files!")
        return 0


def _delete_file(filename, ser_data, ser_command):
    ser_command.flushInput()
    ser_command.write(b"x")  # delete file

    filename = bytes(filename, "utf-8")
    ser_command.write(filename)

    b_success = ser_data.read_until(b"x")
    b_success = int(b_success.decode("ascii").strip("x"))
    if b_success:
        return 1
    else:
        print("Error deleting file!!")
        return 0


def _close_serial(ser_data, ser_command):
    ser_data.close()
    ser_command.close()


def read_file(filename, file_size):
    ser_data, ser_command = establish_serial()
    filename_term = filename + "x"
    filename_term = bytes(filename_term, "utf-8")

    sd_buff_size = 5120
    num_buffs = file_size / sd_buff_size
    print("Original num buffs = ", num_buffs)

    if file_size % sd_buff_size != 0:
        print("chopping last buffer")
        num_buffs = file_size // sd_buff_size
        print("New num buffs = ", num_buffs)
    num_buffs = int(num_buffs)
    bytes_received = []

    ser_command.write(b"o")  # open target file
    ser_data.write(filename_term)

    sd_buff = bytes()
    sd_buff_idx = 0

    for i in range(num_buffs):
        ser_command.write(b"t")
        timer = time.monotonic()

        while sd_buff_idx < sd_buff_size:
            num_read = min(int(ser_data.in_waiting), sd_buff_size - sd_buff_idx)
            if num_read > 0:
                bytesIn = ser_data.read(num_read)
                sd_buff_idx += num_read
                sd_buff += bytesIn
                timer = time.monotonic()

        bytes_received.extend(sd_buff)
        sd_buff = bytes()
        sd_buff_idx = 0

    ser_command.write(b"c")  # close target file
    _close_serial(ser_data, ser_command)
    return bytes_received


def bytes_to_file(my_bytes, filename, filepath="tmp_{}".format(int(time.time()))):
    if not os.path.exists(filepath):
        os.mkdir(filepath)

    full_filepath = Path(filepath, filename)
    with open(full_filepath, "wb") as f:
        f.write(bytes(my_bytes))
    return filepath


def download_all():
    my_filenames = list_files()
    my_file_sizes = file_sizes()
    if not len(my_filenames):
        return []
    dir_name = "tmp_{}".format(int(time.time()))

    filepaths = [
        bytes_to_file(read_file(filename, file_size), filename, dir_name)
        for filename, file_size in zip(my_filenames, my_file_sizes)
    ]

    return filepaths[-1]


def put_device_ID(device_ID):
    ser_data, ser_command = establish_serial()
    ser_command.write(b"p")  # eeprom put
    device_ID_OG = device_ID
    device_ID += "x"
    print("device_ID to write = ", device_ID)
    ser_data.write(bytes(device_ID, "utf-8"))
    while ser_data.in_waiting < len(device_ID) - 1:
        pass

    check_device_ID = ser_data.read_all().decode("utf-8")
    print("Device ID is: ", check_device_ID)

    _close_serial(ser_data, ser_command)
    if check_device_ID == device_ID_OG:
        return True
    else:
        return False


def get_device_ID():
    ser_data, ser_command = establish_serial()
    ser_command.write(b"g")
    device_ID = b""
    while b"x" not in device_ID:
        if ser_data.in_waiting > 0:
            device_ID += ser_data.read(ser_data.in_waiting)
    device_ID = device_ID.decode("utf-8")

    _close_serial(ser_data, ser_command)

    return device_ID[:-1]


def put_fw_ver(fw_ver):
    ser_data, ser_command = establish_serial()
    _flush_all(ser_data, ser_command)
    ser_command.write(b"b")  # eeprom put device

    fw_ver_OG = fw_ver
    fw_ver += "x"
    ser_data.write(bytes(fw_ver, "utf-8"))
    while ser_data.in_waiting < len(fw_ver) - 1:
        pass

    check_fw_ver = ser_data.read_all().decode("utf-8")
    print(fw_ver)

    _close_serial(ser_data, ser_command)

    if check_fw_ver == fw_ver_OG:
        return True
    else:
        return False


def get_fw_ver():
    ser_data, ser_command = establish_serial()
    _flush_all(ser_data, ser_command)
    ser_command.write(b"a")
    fw_ver = b""
    while b"x" not in fw_ver:
        if ser_data.in_waiting > 0:
            fw_ver += ser_data.read(ser_data.in_waiting)
    fw_ver = fw_ver.decode("utf-8")
    ser_data.close()
    return fw_ver[:-1]


def process_data_file(filepath, filename):
    """Struct format from FIRMWARE!

    # struct datrec {
    #   uint32_t microtime;   // millis() since collection start when collection occurred
    #   uint16_t a0;
    #   uint16_t a1;
    #   uint16_t a2;
    #   uint16_t a3;
    #   uint16_t a4;
    #   uint16_t a5;
    #   uint16_t a6;
    #   uint16_t a7;
    #   uint16_t a8;
    #   uint16_t a9;
    #   uint16_t a10;
    #   uint16_t a11;
    #   uint16_t a12;
    #   uint16_t a13;
    #   uint16_t a14;
    #   uint16_t a15;
    #   uint16_t a16;
    #   uint16_t a17;
    #   float gx;
    #   float gy;
    #   float gz;
    #   float wx;
    #   float wy;
    #   float wz;
    #   float Tx;
    #   float Ty;
    #   float Tz;
    # };"""
    # This function returns a pandas Data Frame object with Cass Logger Data pulled from a binary file
    full_filename = Path(filepath, filename)
    dt = np.dtype(
        [
            ("tmicros", "i4"),
            ("d0", "i2"),
            ("d1", "i2"),
            ("d2", "i2"),
            ("e0", "i2"),
            ("e1", "i2"),
            ("e2", "i2"),
            ("f0", "i2"),
            ("f1", "i2"),
            ("f2", "i2"),
            ("c0", "i2"),
            ("c1", "i2"),
            ("c2", "i2"),
            ("a0", "i2"),
            ("a1", "i2"),
            ("a2", "i2"),
            ("b0", "i2"),
            ("b1", "i2"),
            ("b2", "i2"),
            ("gx", "f4"),
            ("gy", "f4"),
            ("gz", "f4"),
            ("wx", "f4"),
            ("wy", "f4"),
            ("wz", "f4"),
            ("Tx", "f4"),
            ("Ty", "f4"),
            ("Tz", "f4"),
        ]
    )
    data = np.fromfile(full_filename, dtype=dt)
    df = pd.DataFrame(data)
    df["tmicros"] = df["tmicros"].apply(lambda x: x - df["tmicros"].iloc[0])
    df.insert(1, "t", df["tmicros"].apply(lambda x: x * 1e-6))
    cols = [
        "tmicros",
        "t",
        "a0",
        "a1",
        "a2",
        "b0",
        "b1",
        "b2",
        "c0",
        "c1",
        "c2",
        "d0",
        "d1",
        "d2",
        "e0",
        "e1",
        "e2",
        "f0",
        "f1",
        "f2",
        "gx",
        "gy",
        "gz",
        "wx",
        "wy",
        "wz",
        "Tx",
        "Ty",
        "Tz",
    ]
    df = df[cols]
    return df
