"""
Example: Download data from a connected Cass Logger and plot internal IMU data.

This script demonstrates how to download binary files from a live device and
visualize the on-board accelerometer channels.

Workflow
--------
1. ``download_data`` — connects to a Cass Logger over serial, downloads all
   recorded ``.bin`` files via ``CassCommands.download_all()``, and returns
   the path to the timestamped download directory.
2. ``plot_internal_imu_data`` — iterates over every ``.bin`` file in that
   directory, parses each one with ``CassCommands.process_data_file``, and
   renders a three-panel time-series plot of the internal IMU axes.
3. ``test_delete`` — lists files on the device, prompts the user for
   confirmation, then deletes all files from the SD card.

Data columns used
-----------------
- ``t``  : elapsed time in seconds (derived from the ``tmicros`` field)
- ``gx`` : internal IMU X-axis acceleration [m/s²]
- ``gy`` : internal IMU Y-axis acceleration [m/s²]
- ``gz`` : internal IMU Z-axis acceleration [m/s²]

Notes
-----
- A Cass Logger must be connected over USB/serial before running this script.
- ``process_data_file`` defaults to the ``"std"`` firmware dtype; pass the
  ``fw_ver`` keyword if the file was recorded with an I2C firmware variant.

Usage
-----
Run directly::

    python examples/download_and_plot_ex.py
"""

import cass_logger_dev.cass_commands as cass_commands
from pathlib import Path
from matplotlib import pyplot as plt
import pandas as pd

FORK_GAIN = 4.884e-02
SHOCK_GAIN = 2.442e-02

cass_util = cass_commands.CassCommands()


def download_data():
    """Download example data from a connected Cass Logger.

    Returns
    -------
    Path
        Path to the directory where the data was downloaded.
    """
    return cass_util.download_all()


def plot_internal_imu_data(data_dir: str):
    """Plot internal IMU gyroscope data (gx, gy, gz) against time.

    NOTE: This is for the existing data in the examples/data dir.

    Reads all .bin files in the given directory and renders a three-panel
    time-series figure of the gyroscope channels using matplotlib.

    Parameters
    ----------
    data_dir : str
        Path to the directory containing .bin data files.
    """
    for file in Path(data_dir).glob("*.bin"):
        example_data = cass_util.process_data_file(file)
        plt.style.use("ggplot")

        fig, axs = plt.subplots(nrows=3, ncols=1, sharex=True, figsize=(12, 8))
        for ax in axs:
            ax.tick_params(axis="x", labelbottom=True)
        axs[0].plot(example_data["t"], example_data["gx"])
        axs[1].plot(example_data["t"], example_data["gy"])
        axs[2].plot(example_data["t"], example_data["gz"])

        # labeling / formatting
        axs[0].set_title(f"Internal IMU - X Acceleration {file.name}")
        axs[1].set_title(f"Internal IMU - Y Acceleration {file.name}")
        axs[2].set_title(f"Internal IMU - Z Acceleration {file.name}")
        plt.title("Example data plot")
        axs[0].set_xlabel("time [s]")
        axs[0].set_ylabel("accel [m/s^2]")
        axs[1].set_xlabel("time [s]")
        axs[1].set_ylabel("accel [m/s^2]")
        axs[2].set_xlabel("time [s]")
        axs[2].set_ylabel("accel [m/s^2]")

        plt.tight_layout()
        plt.show()


def test_delete():
    print(cass_util.list_files())
    bSuccess = cass_util.delete_all_files(prompt_user=True)
    if bSuccess:
        print("Success!!!")
    print(cass_util.list_files())


if __name__ == "__main__":
    data_dir = download_data()
    print(data_dir)
    plot_internal_imu_data(data_dir)
    test_delete()
