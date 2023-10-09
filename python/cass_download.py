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

# PORT_NAME = '/dev/tty.usbmodem136344901' # You can manually set port name

def get_serial_port():
    ports = serial.tools.list_ports.comports()
    # TODO: windows compatability
    logger_ports = [port.device for port in ports if "usbmodem" in port.device]
    if len(logger_ports) != 1:
        print("In cass_commands.get_serial_port()")
        print("Error! More than one teensy port found!")
        return None
    else:
        return logger_ports[0]


def establish_serial(baud_rate=9600):
    serial_port=get_serial_port()
    ser = serial.Serial(serial_port, baud_rate)
    if not ser.is_open:
        ser.open()
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def list_files():
    ser = establish_serial()
    ser.write(b'l')
    
    result = b''
    while b"xxx" not in result:
        if ser.in_waiting > 0:
            result += ser.read(ser.in_waiting)
    result = result.decode('utf-8')
    
    ser.close()
    
    return result.splitlines()[:-1]


def file_sizes():
    ser = establish_serial()

    files = list_files()
    num_files = len(files)

    ser.write(b'z')
    
    my_file_sizes = []
    my_file_sizes = [int(ser.read_until(b'\n').decode('utf-8').strip(),2) for i in range(num_files)]

    ser.close()

    return my_file_sizes


def _delete_file(filename, ser):
    ser.flushInput()
    ser.write(b'x')

    filename = bytes(filename,'utf-8')
    ser.write(filename)

    b_success = ser.read_until(b'x') 
    b_success = int(b_success.decode('ascii').strip('x'))
    if b_success:
        return 1
    else:
        print("ERROR DELETING FILE!")
        return 0


def delete_all_files():
    ser = establish_serial()
    
    [_delete_file(filename, ser) for filename in list_files()]
    
    ser.close()

    if len(list_files()) == 0:
        return 1
    else:
        print("ERROR DELETING FILES!")
        return 0


def read_file(filename,file_size):
    ser = establish_serial()

    # read file with single blocks
    print("Filename is: ", filename) # DEBUG
    filename_term = filename + 'x'
    filename_term = bytes(filename_term,'utf-8')

    sd_buff_size = 4864
    # usbBuffSize = 64
    num_buffs = file_size / sd_buff_size
    print("Original num buffs = ", num_buffs)

    if file_size % sd_buff_size != 0:
        num_buffs = file_size // sd_buff_size # skip last sd_buffer
    num_buffs = int(num_buffs)
    bytes_received = [] # ATTN maybe prealocate with file size

    ser.write(b'o')
    ser.write(filename_term)
    
    sd_buff = bytes()
    sd_buff_idx = 0

    for i in range(num_buffs):
        ser.write(b't')

        while sd_buff_idx < sd_buff_size:
            num_read = min(int(ser.in_waiting), sd_buff_size-sd_buff_idx)
            if num_read>0:
                bytesIn = ser.read(num_read)
                sd_buff_idx += num_read
                sd_buff += bytesIn

        bytes_received.extend(sd_buff)
        sd_buff = bytes()
        sd_buff_idx = 0

    ser.write(b'c')
    ser.close()
    return bytes_received


def bytes_to_file(my_bytes,filename,filepath='tmp_{}'.format(int(time.time()))):
    if not os.path.exists(filepath):
        os.mkdir(filepath)

    full_filepath = Path(filepath,filename)
    with open(full_filepath, "wb") as f:
        f.write(bytes(my_bytes))
    return filepath


def download_all():
    my_filenames = list_files()
    my_file_sizes = file_sizes()
    if not len(my_filenames):
        return []
    dir_name = "tmp_{}".format(int(time.time()))
    
    filepaths = [bytes_to_file(read_file(filename, file_size),filename,dir_name) for filename, file_size in zip(my_filenames, my_file_sizes)]
    
    return filepaths[-1]


def get_device_ID():
    ser = establish_serial()
    ser.write(b'g')
    device_ID = b''
    while b'x' not in device_ID:
        if ser.in_waiting > 0:
            device_ID += ser.read(ser.in_waiting)
    device_ID = device_ID.decode('utf-8')
    return device_ID[:-1]


def get_fw_ver():
    ser = establish_serial()
    ser.write(b'a')
    fw_ver = b''
    while b'x' not in fw_ver:
        if ser.in_waiting > 0:
            fw_ver += ser.read(ser.in_waiting)
    fw_ver = fw_ver.decode('utf-8')
    ser.close()
    return fw_ver[:-1]


def process_data_file(filepath, filename):
    ''' Struct format from logger:
    
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
# };
'''
    # This function returns a pandas Data Frame object with Cass Logger Data pulled from a binary file
    # TODO: need to make firmware key for np data processing handling

    full_filename = Path(filepath,filename)
    # Create a dtype with the binary data format and the desired column names
    dt = np.dtype([('tmicros', 'i4'), ('d0', 'i2'), ('d1', 'i2'), ('d2', 'i2'),
                ('e0', 'i2'), ('e1', 'i2'), ('e2', 'i2'), ('f0', 'i2'), ('f1', 'i2'), ('f2', 'i2'),   
                ('c0', 'i2'), ('c1', 'i2'), ('c2', 'i2'), ('a0', 'i2'), ('a1', 'i2'), ('a2', 'i2'),
                ('b0', 'i2'), ('b1', 'i2'), ('b2', 'i2'), 
                ('gx', 'f4'), ('gy', 'f4'), ('gz', 'f4'), 
                ('wx', 'f4'), ('wy', 'f4'), ('wz', 'f4'), 
                ('Tx', 'f4'), ('Ty', 'f4'), ('Tz', 'f4')])
    data = np.fromfile(full_filename, dtype=dt)
    df = pd.DataFrame(data)
    df['tmicros'] = df['tmicros'].apply(lambda x: x - df['tmicros'].iloc[0])
    df.insert(1,'t',df['tmicros'].apply(lambda x: x * 1e-6))
    cols = ['tmicros','t','a0','a1','a2','b0','b1','b2','c0','c1','c2','d0','d1','d2','e0','e1','e2','f0','f1','f2','gx','gy','gz','wx','wy','wz','Tx','Ty','Tz']
    df = df[cols]
    return df
