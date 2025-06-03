#!/usr/bin/env python3

#
# (C) 2025, by Lucas Burns, AE0LI; Chip Cuccio, W0CHP
# Pi-Star changes (not many) by Andy Taylor, MW0MWZ
#

#
# This tool is used to send messages to the Nextion screen (when attached)
# to give some status when the MMDVMHost binary is not running.
#

import sys
import os

try:
    import serial
    import configparser
except ImportError:
    sys.exit(1)

def get_display_port():
    config = configparser.ConfigParser()
    config.read('/etc/mmdvmhost')

    try:
        display = config.get('General', 'Display').strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        display = None

    # Default fallback
    displayPort = "/dev/ttyAMA0"

    if display == "Nextion":
        try:
            nextion_port = config.get('Nextion', 'Port').strip()
            if nextion_port == "/dev/ttyNextionDriver":
                try:
                    driver_port = config.get('NextionDriver', 'Port').strip()
                    displayPort = driver_port if driver_port else nextion_port
                except (configparser.NoSectionError, configparser.NoOptionError):
                    displayPort = nextion_port
            else:
                displayPort = nextion_port
        except (configparser.NoSectionError, configparser.NoOptionError):
            pass

    if displayPort == "modem":
        try:
            modem_port = config.get('Modem', 'UARTPort').strip()
            if modem_port:
                displayPort = modem_port
        except (configparser.NoSectionError, configparser.NoOptionError):
            pass

    if not os.path.exists(displayPort):
        sys.exit(0)

    return displayPort

MODEM_BAUDRATE = 115200
MMDVM_SERIAL = 0x80

NEXTION_FIELDS = ["t0", "t1", "t2", "t5", "t20", "t30", "t31", "t32"] # <https://repo.w0chp.net/WPSD-Dev/WPSD_Nextion/src/branch/main/Nextion_Field_Use.md#nextion-display-fields>

def MakeNextionCommand(commandString: str):
    result = bytearray()
    result.extend(commandString.encode())
    result.extend([0xff, 0xff, 0xff])
    return result

def MakeSetTextCommandString(field, value):
    return f"{field}.txt=\"{value}\""

def MakeModemCommand(nextionCommand: bytearray):
    frameLength = len(nextionCommand) + 3
    result = bytearray([0xe0, frameLength, MMDVM_SERIAL])
    result.extend(nextionCommand)
    return result

def SendModemCommand(mmdvmCommand: bytearray, serialInterface: serial.Serial):
    serialInterface.write(mmdvmCommand)

def SetTextValue(field, value, serialInterface: serial.Serial):
    command = MakeModemCommand(MakeNextionCommand(MakeSetTextCommandString(field, value)))
    SendModemCommand(command, serialInterface)

def ClearAllFields(serialInterface: serial.Serial):
    for field in NEXTION_FIELDS:
        SetTextValue(field, "", serialInterface)
    SendModemCommand(MakeModemCommand(MakeNextionCommand("ref 0")), serialInterface)

if __name__ == "__main__":
    programPath = sys.argv[0]
    programName = os.path.basename(programPath)

    port = get_display_port()

    if port is None:
        print(f"Failed to get the display port from configuration.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(f"Usage: {programName} [-c | <field> <text value>]")
        sys.exit()

    try:
        serialInterface = serial.Serial(port=port, baudrate=MODEM_BAUDRATE)

        if sys.argv[1] == "-c":
            ClearAllFields(serialInterface)
        elif len(sys.argv) == 3:
            field = sys.argv[1]
            textValue = sys.argv[2]
            SetTextValue(field, textValue, serialInterface)
        else:
            print(f"Invalid arguments. Usage: {programName} [-c | <field> <text value>]")
            sys.exit()

        serialInterface.close()

    except serial.SerialException as e:
        print(f"Serial port exception: {e}")
        sys.exit()
