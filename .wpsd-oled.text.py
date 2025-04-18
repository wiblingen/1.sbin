#!/usr/bin/env python3

#
# (C) 2025, by Andy Taylor MW0MWZ
#
# Extended my Chip Cuccio, W0CHP
#
# This tool is used to send messages to the OLED screen (when attached)
# to give some status when the MMDVMHost binary is not running.
#

import sys
import subprocess
import argparse
import configparser
import os

try:
    from PIL import Image, ImageDraw, ImageFont
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306, sh1106
except ImportError as e:
    print(f"Error: Failed to import required libraries.", file=sys.stderr)
    print(f"Ensure 'Pillow' and 'luma.oled' are installed.", file=sys.stderr)
    print(f"Specific error: {e}", file=sys.stderr)
    sys.exit(1)

CONFIG_PATH = "/etc/mmdvmhost"
DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def load_font(font_path, size):
    font = None
    try:
        if os.path.exists(font_path): font = ImageFont.truetype(font_path, size)
        else: font = ImageFont.load_default()
    except Exception as e: font = ImageFont.load_default()
    if font is None: font = ImageFont.load_default()
    return font

def get_text_dimensions(text, font):
    try:
        dummy_img = Image.new('1', (1, 1)); dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            width = font.getlength(text)
            bbox_a = dummy_draw.textbbox((0, 0), "A", font=font)
            height = bbox_a[3]-bbox_a[1] if bbox_a else 8
            return width, height
        except: return 0, 8

def get_config_settings():
    screen_type, address, rotate_config_value = None, None, 0
    try:
        if not os.path.exists(CONFIG_PATH):
            print(f"Error: Config file not found: {CONFIG_PATH}", file=sys.stderr)
            return None, None, None

        config = configparser.ConfigParser()
        config.read(CONFIG_PATH)

        if not config.has_section("OLED"):
            print(f"Error: Missing [OLED] section in {CONFIG_PATH}", file=sys.stderr)
            return None, None, None

        if config.has_option("OLED", "Type"):
            try:
                type_int = config.getint("OLED", "Type")
                if type_int == 3: screen_type, address = 'type3', 0x3C
                elif type_int == 6: screen_type, address = 'type6', 0x3C
                else: print(f"Warning: Unsupported OLED Type '{type_int}'. Check config.", file=sys.stderr)
            except ValueError:
                 print(f"Warning: Invalid Type format in config. Must be an integer.", file=sys.stderr)
        else:
             print(f"Error: Missing 'Type' option in [OLED] section of {CONFIG_PATH}", file=sys.stderr)
             return None, None, None

        if config.has_option("OLED", "Address"):
            try:
                address = int(config.get("OLED", "Address"), 16)
            except ValueError:
                print(f"Warning: Invalid Address format in config. Using default: {address:#04x}", file=sys.stderr)

        if config.has_option("OLED", "Rotate"):
            try:
                rotate_config_value = config.getint("OLED", "Rotate")
                if rotate_config_value not in [0, 1]:
                     print(f"Warning: Invalid Rotate value '{rotate_config_value}'. Must be 0 or 1. Defaulting to 0.", file=sys.stderr)
                     rotate_config_value = 0
            except ValueError:
                 print(f"Warning: Invalid Rotate format in config. Must be 0 or 1. Defaulting to 0.", file=sys.stderr)
                 rotate_config_value = 0
        else:
             print(f"Info: 'Rotate' option not found in [OLED] section. Defaulting to 0 (no rotation).", file=sys.stderr)
             rotate_config_value = 0

        return screen_type, address, rotate_config_value

    except Exception as e:
        print(f"Error reading config: {e}", file=sys.stderr)
        return None, None, None

def clear_display(device):
    try: device.clear()
    except Exception as e: print(f"Error clearing display: {e}", file=sys.stderr)

def draw_text(device, line1, size1, line2, size2):
    try:
        width = device.width; height = device.height
        font1 = load_font(DEFAULT_FONT_PATH, size1)
        font2 = load_font(DEFAULT_FONT_PATH, size2)
        image_mode = getattr(device, 'mode', '1'); image = Image.new(image_mode, (width, height)); draw = ImageDraw.Draw(image)

        text_width_1, text_height_1 = get_text_dimensions(line1, font1)
        text_width_2, text_height_2 = get_text_dimensions(line2, font2)

        x1 = max(0, (width - text_width_1) // 2)
        x2 = max(0, (width - text_width_2) // 2)

        total_h = text_height_1 + text_height_2; spacing = max(1, (height - total_h) // 3)
        y1 = spacing; y2 = y1 + text_height_1 + spacing
        if y2 + text_height_2 > height:
            spacing = max(0, (height - total_h) // 3); y1, y2 = spacing, y1 + text_height_1 + spacing
            if y2 + text_height_2 > height:
                y1, y2 = 0, text_height_1 + 1
                if y2 + text_height_2 > height: y2 = height - text_height_2; y1 = max(0, y2 - text_height_1 - 1)

        draw.text((x1, y1), line1, font=font1, fill="white")
        draw.text((x2, y2), line2, font=font2, fill="white")
        device.display(image)
    except Exception as e:
        print(f"Error drawing text: {e}", file=sys.stderr)
        raise e

def main():
    script_name = os.path.basename(sys.argv[0])
    parser = argparse.ArgumentParser(prog=script_name, description="Control OLED display based on /etc/mmdvmhost config.", add_help=False)
    required_group = parser.add_argument_group('Display Options (Required unless -c)')
    required_group.add_argument('--text1', type=str, help="Text for line 1.")
    required_group.add_argument('--size1', type=int, default=12, help="Font size for line 1 (default: 12).")
    required_group.add_argument('--text2', type=str, help="Text for line 2.")
    required_group.add_argument('--size2', type=int, default=12, help="Font size for line 2 (default: 12).")
    action_group = parser.add_argument_group('Action')
    action_group.add_argument('-c', '--clear', action='store_true', help="Clear the display.")
    parser.add_argument('-h', '--help', action='help', default=argparse.SUPPRESS, help='Show this help message and exit.')

    args = parser.parse_args()

    if len(sys.argv) == 1: parser.print_help(); sys.exit(0)

    if args.clear: pass
    else:
        if not args.text1 or not args.text2: parser.error("--text1 and --text2 required unless -c.")
        if args.size1 <= 0 or args.size2 <= 0: parser.error("--size1, --size2 must be positive.")

    screen_type, address, rotate_config_value = get_config_settings()
    if screen_type is None or address is None or rotate_config_value is None:
         print(f"Error: Failed to retrieve necessary OLED configuration from {CONFIG_PATH}. Exiting.", file=sys.stderr)
         sys.exit(1)

    rotation_value = 2 if rotate_config_value == 1 else 0

    device = None

    try:
        serial = i2c(port=1, address=address)
        device_width, device_height = 128, 64

        if screen_type == 'type3':
            device = ssd1306(serial, width=device_width, height=device_height, rotate=rotation_value)
        elif screen_type == 'type6':
            device = sh1106(serial, width=device_width, height=device_height, rotate=rotation_value)
        else:
            print(f"Error: Invalid screen type '{screen_type}' determined from config.", file=sys.stderr)
            sys.exit(1)

        device.cleanup = lambda: None

        if args.clear:
            clear_display(device)
        else:
            draw_text(device, args.text1, args.size1, args.text2, args.size2)

    except FileNotFoundError: print(f"Error: I2C bus not found (is i2c enabled and device connected?).", file=sys.stderr); sys.exit(1)
    except OSError as e: print(f"Error communicating via I2C at address {address:#04x}: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
