import cass_download


# example for setting and getting RTC time
def main():
    print(cass_download.get_RTC_time())
    print(f"RTC Success = {cass_download.set_RTC_time()}")
    print(cass_download.get_RTC_time())


if __name__ == "__main__":
    main()
