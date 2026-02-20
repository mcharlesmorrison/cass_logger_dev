import src.cass_commands as cass_commands


# example for setting and getting RTC time
def main():
    cass_util = cass_commands.CassCommands()
    print(cass_util.get_RTC_time())
    print(f"RTC Success = {cass_commands.set_RTC_time()}")
    print(cass_util.get_RTC_time())


if __name__ == "__main__":
    main()
