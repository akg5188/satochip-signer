import os
import subprocess
import tempfile

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import CircleModuleDrawer, GappedSquareModuleDrawer
from PIL import Image, ImageColor, ImageDraw


def _normalize_qr_render_data(data):
    if isinstance(data, str) and data.lower().startswith("ur:eth-signature/"):
        # Keep outgoing eth-signature result QRs in uppercase so picky wallet
        # scanners like OKX can decode a less dense alphanumeric-mode QR. Do not
        # apply this to connection URs such as crypto-multi-accounts; some wallets
        # are stricter there and expect the original canonical casing.
        return data.upper()
    return data


def _qr_background_rgba(background_color):
    if not isinstance(background_color, str):
        return (255, 255, 255, 255)
    normalized = background_color if background_color.startswith("#") else f"#{background_color}"
    try:
        rgb = ImageColor.getrgb(normalized)
    except ValueError:
        rgb = (255, 255, 255)
    return (*rgb, 255)


def _build_qr(data, border: int):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr


def _render_box_size(qr, width: int, height: int, border: int) -> int:
    total_modules = qr.modules_count + 2 * border
    if total_modules <= 0:
        return 1
    return max(1, min(width, height) // total_modules)


def _finalize_qr_image(img, width: int, height: int, background_color):
    img = img.convert("RGBA")
    target_size = max(1, min(width, height))

    # Always expand or shrink the QR to the largest square that fits on the
    # display so dense payloads do not stay tiny just because their source
    # render landed on a 1px module size.
    if img.size != (target_size, target_size):
        img = img.resize((target_size, target_size), Image.Resampling.NEAREST).convert("RGBA")

    if width == target_size and height == target_size:
        return img

    canvas = Image.new("RGBA", (width, height), _qr_background_rgba(background_color))
    x = (width - target_size) // 2
    y = (height - target_size) // 2
    canvas.paste(img, (x, y))
    return canvas


class QR:
    STYLE__DEFAULT = 1
    STYLE__ROUNDED = 2
    STYLE__GRID = 3

    def __init__(self) -> None:
        return


    def qrsize(self, data) -> int:
        data = _normalize_qr_render_data(data)
        border = 3
        qr = _build_qr(data, border)
        return qr.modules_count


    def qrimage(self, data, width=240, height=240, border=3, style=None, background_color="#444", box_size_override=None):
        data = _normalize_qr_render_data(data)
        qr = _build_qr(data, border)
        qr.box_size = box_size_override or _render_box_size(qr, width, height, border)
        box_size = qr.box_size
        if not style or style == QR.STYLE__DEFAULT:
            img = qr.make_image(
                fill_color="black",
                back_color=background_color
            )
            return _finalize_qr_image(img, width, height, background_color)
        else:
            if style == QR.STYLE__ROUNDED:
                qr_image = qr.make_image(
                    fill_color="black",
                    back_color=background_color,
                    image_factory=StyledPilImage,
                    module_drawer=CircleModuleDrawer()
                )

                qr_image_width, _ = qr_image.size
                qr_code_dims = int(qr_image_width / box_size) - 2*border

                if qr_code_dims > 21:
                    # The ROUNDED style mis-renders the small lower-right registration box in 25x25, 29x29,
                    # and 33x33.
                    draw = ImageDraw.Draw(qr_image)
                    if qr_code_dims == 25:
                        # registration block starts at 16, 16 and is 5x5
                        starting_point = 16 + border

                    elif qr_code_dims == 29:
                        # The registration block starts at 20,20 and is 5x5
                        starting_point = 20 + border
                    
                    elif qr_code_dims == 33:
                        # The registration block starts at 24,24 and is 5x5
                        starting_point = 24 + border
                    
                    else:
                        raise Exception(f"Unrecognized qrimage size: {qr_code_dims}")
                    
                    # Render black rectangular lines on top of the qr_image to square off
                    # the registration block.
                    lines = [
                        (
                            # top
                            (starting_point*box_size, starting_point*box_size),
                            (starting_point*box_size + 5*box_size - 1, starting_point*box_size + box_size - 1)
                        ),
                        (
                            # right
                            (starting_point*box_size + 4*box_size, starting_point*box_size),
                            (starting_point*box_size + 5*box_size - 1, starting_point*box_size + 5*box_size - 1)
                        ),
                        (
                            # left
                            (starting_point*box_size, starting_point*box_size),
                            (starting_point*box_size + box_size - 1, starting_point*box_size + 5*box_size - 1)
                        ),
                        (
                            # bottom
                            (starting_point*box_size + box_size, starting_point*box_size + 4*box_size),
                            (starting_point*box_size + 5*box_size - 1, starting_point*box_size + 5*box_size - 1)
                        ),
                        (
                            # center dot
                            (starting_point*box_size + 2*box_size, starting_point*box_size + 2*box_size),
                            (starting_point*box_size + 3*box_size - 1, starting_point*box_size + 3*box_size - 1)
                        )
                    ]

                    for line in lines:
                        draw.rectangle(line, fill="black")

                return _finalize_qr_image(qr_image, width, height, background_color)

            elif style == QR.STYLE__GRID:
                img = qr.make_image(
                    fill_color="black",
                    back_color=background_color,
                    image_factory=StyledPilImage,
                    module_drawer=GappedSquareModuleDrawer()
                )
                return _finalize_qr_image(img, width, height, background_color)


    def qrimage_io(self, data, width=240, height=240, border=3, background_color="808080"):
        import re

        data = _normalize_qr_render_data(data)

        if 1 <= border <= 10:
            border_str = str(border)
        else:
            border_str = "3"

        # Validate background_color to prevent argument injection
        if not re.fullmatch(r'[0-9A-Fa-f]{6}', background_color):
            background_color = "808080"
        background_hex = f"#{background_color}"

        if isinstance(data, str):
            encoded_data = data.encode()
            is_binary = False
        else:
            encoded_data = data
            is_binary = True

        qr = _build_qr(data, border)
        box_size = _render_box_size(qr, width, height, border)
        data_path = None
        output_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False) as data_file:
                data_file.write(encoded_data)
                data_file.flush()
                data_path = data_file.name

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as output_file:
                output_path = output_file.name

            cmd = [
                "qrencode",
                "-m", border_str,
                "-s", str(box_size),
                "-l", "L",
                f"--foreground=000000",
                f"--background={background_color}",
                "-t", "PNG",
            ]
            if is_binary:
                cmd.append("-8")
            cmd.extend(["-r", data_path, "-o", output_path])

            try:
                rv = subprocess.call(cmd)
            except FileNotFoundError:
                # `qrencode` may be unavailable in some test/dev environments.
                # Fall back to the pure-Python encoder path in that case.
                rv = 1

            # If `qrencode` is unavailable, keep the requested background color
            # when falling back to the pure-Python renderer.
            if rv != 0:
                return self.qrimage(
                    data,
                    width,
                    height,
                    border,
                    background_color=background_hex,
                    box_size_override=3,
                )

            with Image.open(output_path) as img_file:
                img = _finalize_qr_image(img_file, width, height, background_hex)

            return img
        finally:
            if data_path and os.path.exists(data_path):
                os.remove(data_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
