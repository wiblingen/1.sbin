#!/usr/bin/env python3

#
##############################################
#                                            #
#        WPSD Modem Detection Utility        #
#           (C) Chip Cuccio - W0CHP          #
#                                            #
##############################################
#

import os
import sys
import time
import subprocess
import serial
import glob
import re
import platform
import argparse
import shutil
import psutil

MMDVM_GET_VER = b'\xE0\x03\x00'
DVMEGA_GET_VER = b'\xD0\x01\x00\x11\x00\x0B'
NEXTION_CLEAR = b'\xFF\xFF\xFF'
NEXTION_CONNECT = b'connect'

SERIAL_READ_TIMEOUT = 0.2

def run_command(cmd_list, check=False, capture_output=False, text=False, shell=False):
    try:
        process = subprocess.run(
            cmd_list,
            check=check,
            capture_output=capture_output,
            text=text,
            shell=shell
        )
        if process.returncode != 0 and check:
            err_msg = process.stderr.strip() if capture_output and process.stderr else f"Command failed with return code {process.returncode}"
            print(f"Error running command {' '.join(cmd_list)}: {err_msg}", file=sys.stderr)
            return None
        return process
    except FileNotFoundError:
        print(f"Error: Command not found: {cmd_list[0]}", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else f"Command failed with return code {e.returncode}"
        print(f"Error running command {' '.join(cmd_list)}: {err_msg}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error executing {' '.join(cmd_list)}: {e}", file=sys.stderr)
        return None

def get_hardware_type():
    try:
        if not os.path.exists("/etc/WPSD-release"):
            return "Unknown"
        with open("/etc/WPSD-release", "r") as f:
            for line in f:
                if line.lower().startswith("hardware"):
                    parts = line.split("= ", 1)
                    if len(parts) > 1:
                        return parts[1].strip()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Warning: Could not read /etc/WPSD-release: {e}", file=sys.stderr)
    return "Unknown"

def get_platform_type():
    detector_script = "/usr/local/sbin/.wpsd-platform-detect"
    if not os.path.exists(detector_script) or not os.access(detector_script, os.X_OK):
         return platform.machine()

    result = run_command([detector_script], capture_output=True, text=True, check=False)
    if result and result.returncode == 0:
        return result.stdout.strip()
    else:
        return platform.machine()

def get_gpio_base():
    gpio_dir = '/sys/class/gpio'
    chip_numbers = []
    has_rp1 = False

    try:
        if not os.path.isdir(gpio_dir):
             return 0

        for entry in os.listdir(gpio_dir):
            if entry.startswith('gpiochip'):
                chip_path = os.path.join(gpio_dir, entry)
                if os.path.islink(chip_path):
                    try:
                        link_target_path = os.readlink(chip_path)
                        link_target = os.path.basename(link_target_path)
                        device_link = os.path.join(chip_path, 'device')
                        if os.path.islink(device_link):
                            device_target = os.path.basename(os.readlink(device_link))
                            if 'pinctrl-rp1' in device_target:
                                has_rp1 = True
                                break

                        if 'pinctrl-bcm' in link_target or '0000.gpio' in link_target:
                            match = re.search(r'gpiochip(\d+)', entry)
                            if match:
                                chip_numbers.append(int(match.group(1)))
                    except OSError:
                        continue

        if has_rp1:
             return 0

        if chip_numbers:
            chip_numbers.sort()
            base = chip_numbers[-1]
            return 0 if base == 504 else base
        else:
             return 0

    except OSError as e:
        return 0

def gpio_sysfs_write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except (IOError, OSError) as e:
        if e.errno not in [16, 22, 2]:
             print(f"Warning: Could not write to {path}: {e}", file=sys.stderr)
        return False

def reset_gpio_modem():
    base = get_gpio_base()
    pin20 = base + 20
    pin21 = base + 21
    pin20_path = f"/sys/class/gpio/gpio{pin20}"
    pin21_path = f"/sys/class/gpio/gpio{pin21}"

    gpio_sysfs_write("/sys/class/gpio/unexport", pin20)
    gpio_sysfs_write("/sys/class/gpio/unexport", pin21)
    time.sleep(0.1)

    if not gpio_sysfs_write("/sys/class/gpio/export", pin20):
        print(f"Error: Failed to export GPIO {pin20}", file=sys.stderr)
        return
    if not gpio_sysfs_write("/sys/class/gpio/export", pin21):
        print(f"Error: Failed to export GPIO {pin21}", file=sys.stderr)
        gpio_sysfs_write("/sys/class/gpio/unexport", pin20)
        return

    time.sleep(0.1)

    path_pin20_dir = os.path.join(pin20_path, "direction")
    path_pin21_dir = os.path.join(pin21_path, "direction")
    path_pin20_val = os.path.join(pin20_path, "value")
    path_pin21_val = os.path.join(pin21_path, "value")

    if not os.path.exists(path_pin20_dir) or not os.path.exists(path_pin21_dir):
         time.sleep(0.2)
         if not os.path.exists(path_pin20_dir) or not os.path.exists(path_pin21_dir):
             print(f"Error: GPIO {pin20} or {pin21} sysfs nodes not found after export. Aborting reset.", file=sys.stderr)
             gpio_sysfs_write("/sys/class/gpio/unexport", pin20)
             gpio_sysfs_write("/sys/class/gpio/unexport", pin21)
             return

    if not gpio_sysfs_write(path_pin20_dir, "out"): return
    if not gpio_sysfs_write(path_pin21_dir, "out"): return
    time.sleep(0.5)

    gpio_sysfs_write(path_pin20_val, 0)
    gpio_sysfs_write(path_pin21_val, 0)
    time.sleep(0.1)
    gpio_sysfs_write(path_pin21_val, 1)
    time.sleep(1)
    gpio_sysfs_write(path_pin20_val, 1)
    time.sleep(0.1)
    gpio_sysfs_write(path_pin20_val, 0)
    time.sleep(0.5)

    gpio_sysfs_write("/sys/class/gpio/unexport", pin20)
    gpio_sysfs_write("/sys/class/gpio/unexport", pin21)
    time.sleep(2)

def nano_pi_reset():
    gpio_cmd_path = shutil.which('gpio')
    if not gpio_cmd_path:
        print("Error: 'gpio' command not found in PATH. Cannot perform NanoPi GPIO sequence.", file=sys.stderr)
        return

    run_command([gpio_cmd_path, "mode", "3", "out"])
    run_command([gpio_cmd_path, "mode", "4", "out"])
    run_command([gpio_cmd_path, "write", "4", "1"])
    run_command([gpio_cmd_path, "write", "3", "0"])
    time.sleep(1)
    run_command([gpio_cmd_path, "write", "3", "1"])

    stm32flash_cmd = "/usr/local/bin/firmware/utils/stm32flash-0.7"
    if not os.path.exists(stm32flash_cmd) or not os.access(stm32flash_cmd, os.X_OK):
        print(f"Error: '{stm32flash_cmd}' not found or not executable. Cannot perform stm32flash reset.", file=sys.stderr)
        return

    run_command([
        stm32flash_cmd,
        "/dev/ttyAMA0",
        "-R",
        "-i", "200,-3,3:-200,-3,3"
    ])
    time.sleep(2)

def read_device(modem_device, serial_protocol, serial_speed):
    data = b""
    ser = None
    try:
        ser = serial.Serial(
            port=modem_device,
            baudrate=serial_speed,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_READ_TIMEOUT,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            exclusive=True
        )

        command = b''
        if serial_protocol == "mmdvm":
            command = MMDVM_GET_VER
        elif serial_protocol == "dvmega":
            command = DVMEGA_GET_VER
        elif serial_protocol == "nextion":
            ser.write(NEXTION_CLEAR)
            ser.flush()
            time.sleep(0.05)
            ser.write(NEXTION_CONNECT)
            ser.flush()
            time.sleep(0.05)
            ser.write(NEXTION_CLEAR)
            ser.flush()
        else:
            if ser and ser.is_open: ser.close()
            return None

        if command:
            ser.write(command)
            ser.flush()

        data = ser.read(256)

    except serial.SerialException as e:
        if "Permission denied" in str(e):
             print(f"Error: Permission error accessing {modem_device}. Run as root/check group membership.", file=sys.stderr)
        pass
    except Exception as e:
        print(f"Error communicating with {modem_device}: {e}", file=sys.stderr)
    finally:
        if ser and ser.is_open:
            ser.close()

    return data

def clean_printable(byte_data):
    if not byte_data:
        return ""
    decoded_string = byte_data.decode('latin-1', errors='replace')
    return "".join(filter(lambda x: ' ' <= x <= '~', decoded_string))

def check_mmdvm_output(modem_device, serial_speed, data):
    if not data or len(data) < 5:
        return False

    printable_data = clean_printable(data)

    modem_data = ""
    prefixes = ["MMDVM_HS", "D2RG_MMDVM_HS", "ZUMspot", "Nano_", "OpenGD77_HS", "SkyBridge", "EuroNode", "HS_Hat", "MMDVM", "DVMEGA", "DV-MEGA"]
    for prefix in prefixes:
        match = re.search(re.escape(prefix) + r'.*', printable_data)
        if match:
            modem_data = match.group(0).strip()
            if prefix in ["DVMEGA", "DV-MEGA"] and MMDVM_GET_VER == b'\xE0\x03\x00':
                 pass
            break

    if not modem_data:
        if "u-blox" in printable_data or "$GNGSA" in printable_data or "$GPGGA" in printable_data:
             match_gps = re.search(r'(\$G[NP][GSA]{2}[^,\r\n]*|u-blox.*)', printable_data)
             modem_data = match_gps.group(0).strip() if match_gps else "u-blox GPS/GNSS"
        else:
            return False

    mmdvm_class = "Unknown "
    if "MMDVM_HS" in modem_data or "HS_Hat" in modem_data or "ZUMspot" in modem_data or \
       "Nano_" in modem_data or "OpenGD77_HS" in modem_data or "SkyBridge" in modem_data or \
       "EuroNode" in modem_data or "D2RG_MMDVM_HS" in modem_data:
        mmdvm_class = "MMDVM_HS"
    elif "MMDVM" in modem_data:
         mmdvm_class = "MMDVM   "
    elif "DV-MEGA" in modem_data or "DVMEGA" in modem_data:
        mmdvm_class = "DV-Mega "
    elif "GPS" in modem_data or "GNSS" in modem_data or "u-blox" in modem_data or modem_data.startswith('$G'):
        mmdvm_class = "GPS/GNSS"


    mmdvm_port = "GPIO" if "ttyS" in modem_device or "ttyAMA" in modem_device else "USB"

    mmdvm_protocol_ver = "N/A"
    if "MMDVM" in mmdvm_class and len(data) > 3:
        protocol_byte = data[3]
        if protocol_byte == 0x01:
            mmdvm_protocol_ver = "V1"
        elif protocol_byte == 0x02:
            mmdvm_protocol_ver = "V2"
        else:
            mmdvm_protocol_ver = f"Unknown (0x{protocol_byte:02X})"

    if mmdvm_class != "Unknown ":
        print(f"Detected {mmdvm_class.strip()} Port: {modem_device} ({mmdvm_port}) Baud: {serial_speed} Protocol: {mmdvm_protocol_ver}")
        print(f"\t Modem Data: {modem_data}")
        return True

    return False

def check_dvmega_output(modem_device, serial_speed, data):
    if not data or len(data) < 5:
        return False

    try:
        dvmega_data_decoded = data.decode('latin-1')
        dvmega_data_cleaned = "".join(c for c in dvmega_data_decoded if c.isprintable() or c in ['\t', '\n', '\r'])
        dvmega_data_cleaned = dvmega_data_cleaned.strip()
    except UnicodeDecodeError:
         dvmega_data_cleaned = clean_printable(data).strip()

    if not dvmega_data_cleaned:
        return False

    dvmega_port = "GPIO" if "ttyS" in modem_device or "ttyAMA" in modem_device else "USB"

    if "DV-MEGA" in dvmega_data_cleaned or "DVMEGA" in dvmega_data_cleaned:
        print(f"Detected DV-Mega  Port: {modem_device} ({dvmega_port}) Baud: {serial_speed}")
        print(f"\t Modem Data: {dvmega_data_cleaned} - DStarRepeater Protocol")
        return True
    elif "u-blox" in dvmega_data_cleaned or "$GNGSA" in dvmega_data_cleaned or "$GPGGA" in dvmega_data_cleaned:
         match_gps = re.search(r'(\$G[NP][GSA]{2}[^,\r\n]*|u-blox.*)', dvmega_data_cleaned)
         gps_data = match_gps.group(0).strip() if match_gps else "u-blox GPS/GNSS"
         print(f"Detected GPS/GNSS Port: {modem_device} ({dvmega_port}) Baud: {serial_speed}")
         print(f"\t Modem Data: {gps_data}")
         return True

    return False

def check_nextion_output(modem_device, serial_speed, data):
    if not data or len(data) < 10:
        return False

    try:
        comok_pos = data.find(b'comok')
        if comok_pos == -1:
            return False

        nextion_data_decoded = data[comok_pos:].decode('ascii', errors='ignore')
        nextion_data_cleaned = "".join(c for c in nextion_data_decoded if ' ' <= c <= '~')
        nextion_data_cleaned = nextion_data_cleaned.strip()

    except Exception:
         return False

    if nextion_data_cleaned.startswith("comok") and ",NX" in nextion_data_cleaned:
        parts = nextion_data_cleaned.split(',')
        if len(parts) >= 6:
            nextion_model = parts[2] if len(parts) > 2 and len(parts[2]) > 0 else "Unknown"
            nextion_touch_raw = parts[0]
            nextion_serial = parts[5] if len(parts) > 5 and len(parts[5]) > 0 else "Unknown"

            nextion_touch = "Yes" if nextion_touch_raw == "comok 1" else "No"
            nextion_port = "GPIO" if "ttyS" in modem_device or "ttyAMA" in modem_device else "USB"

            print(f"Detected Nextion  Port: {modem_device} ({nextion_port}) Baud: {serial_speed}")
            print(f"\t Model: {nextion_model} Serial: {nextion_serial} Touch: {nextion_touch}")
            return True

    return False

def is_process_running(process_name):
    try:
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'].lower() == process_name.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
         print(f"Warning: Failed to check running processes using psutil: {e}", file=sys.stderr)
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WPSD Modem Detection Utility. Detects MMDVM, DVMEGA, u-blox GPS/GNSS, and Nextion devices.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-r", "--reset",
        action="store_true",
        help="Perform hardware reset sequence before and after scanning."
    )
    parser.add_argument(
        "-d", "--no-service-mgmt",
        action="store_true",
        help="Do not stop/start mmdvmhost.service or mmdvmhost.timer."
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: You need to be root (use 'sudo') to run this script.", file=sys.stderr)
        sys.exit(1)

    hardware_type = get_hardware_type()
    platform_info = get_platform_type()

    svc_restarted = None
    timer_restarted = None
    if not args.no_service_mgmt:
        if is_process_running('MMDVMHost'):
            run_command(['systemctl', 'stop', 'mmdvmhost.timer'], check=False)
            time.sleep(0.2)
            stop_result = run_command(['systemctl', 'stop', 'mmdvmhost.service'], check=True)
            if stop_result:
                svc_restarted = 'mmdvmhost.service'
                time.sleep(1)

    if args.reset:
        if hardware_type == "NanoPi":
            nano_pi_reset()
        else:
            reset_gpio_modem()

    potential_devices = []
    for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*', '/dev/ttyAMA*', '/dev/ttyS*']:
        potential_devices.extend(glob.glob(pattern))

    devices_to_scan = []
    scanned_paths = set()

    for dev in potential_devices:
        try:
            dev_path = os.path.realpath(dev)
            if dev_path in scanned_paths:
                continue

            if not os.path.exists(dev_path) or not (os.stat(dev_path).st_mode & 0o020000):
                continue
        except OSError:
            continue

        dev_base = os.path.basename(dev_path)

        if platform_info.lower().startswith("odroid") and dev_base.startswith("ttyS") and not dev_base.startswith("ttySAC"):
             continue
        if hardware_type == "NanoPi" and dev_base == "ttyS0":
             continue
        if dev_base.startswith("ttySC") or dev_base == "ttyS0":
             continue
        if dev_base == 'tty':
             continue

        devices_to_scan.append(dev_path)
        scanned_paths.add(dev_path)


    if not devices_to_scan:
        print("Warning: No suitable serial devices found to scan.", file=sys.stderr)

    for modem_device in devices_to_scan:
        device_found_on_port = False

        for speed in [115200, 460800, 230400]:
            if device_found_on_port: break
            response_data = read_device(modem_device, "mmdvm", speed)
            if response_data:
                if check_mmdvm_output(modem_device, speed, response_data):
                    device_found_on_port = True

        if not device_found_on_port:
            speed = 115200
            response_data = read_device(modem_device, "dvmega", speed)
            if response_data:
                if check_dvmega_output(modem_device, speed, response_data):
                     device_found_on_port = True
                elif check_mmdvm_output(modem_device, speed, response_data):
                     device_found_on_port = True

        if not device_found_on_port:
            for speed in [9600, 115200, 57600, 38400, 19200, 2400, 4800, 31250, 230400, 250000, 256000, 460800, 512000, 921600]:
                 if device_found_on_port: break
                 response_data = read_device(modem_device, "nextion", speed)
                 if response_data:
                     if check_nextion_output(modem_device, speed, response_data):
                         device_found_on_port = True

    if args.reset:
        if hardware_type == "NanoPi":
            nano_pi_reset()
        else:
            reset_gpio_modem()

    if svc_restarted:
        start_service_result = run_command(['systemctl', 'start', svc_restarted], check=True)
        if start_service_result:
            time.sleep(0.5)
            run_command(['systemctl', 'start', 'mmdvmhost.timer'], check=False)
        else:
            run_command(['systemctl', 'status', '--no-pager', '-l', svc_restarted])

    sys.exit(0)
