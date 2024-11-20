import cass_download
from pathlib import Path
from matplotlib import pyplot as plt


def main():
    my_data = cass_download.process_data_file(
        str(Path.cwd()), "0a692d0e-2052-47f3-92c4-0571bded6ace.bin"
    )
    plt.plot(my_data["t"], my_data["a0"])
    plt.title("Example data plot (potentiometer data)")
    plt.xlabel("time [s]")
    plt.ylabel("Potentiometer output (uncalibrated)")
    plt.show()


if __name__ == "__main__":
    main()
