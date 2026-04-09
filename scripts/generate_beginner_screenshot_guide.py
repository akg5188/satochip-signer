#!/usr/bin/env python3

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets" / "beginner-screenshot-guide"

CANVAS = (1500, 900)
BG = "#f6f1e8"
PANEL = "#fffaf2"
INK = "#1f2430"
MUTED = "#55606f"
GREEN = "#3b8f63"
GREEN_SOFT = "#daf0e3"
BLUE = "#244d80"
BLUE_SOFT = "#dde9f8"
ORANGE = "#c46a2b"
ORANGE_SOFT = "#f7e3d3"
BORDER = "#d5c8b8"
PHONE = "#161819"
PI_CASE = "#20364f"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


FONT_H1 = load_font(44, bold=True)
FONT_H2 = load_font(28, bold=True)
FONT_H3 = load_font(22, bold=True)
FONT_BODY = load_font(22)
FONT_SMALL = load_font(18)


def rounded_box(draw: ImageDraw.ImageDraw, box, fill, outline=BORDER, width=2, radius=28):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    lines = []
    for paragraph in text.splitlines():
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def draw_multiline(draw: ImageDraw.ImageDraw, text: str, font, fill, x: int, y: int, max_width: int, line_gap: int = 8):
    lines = wrapped_lines(draw, text, font, max_width)
    cursor_y = y
    for line in lines:
        draw.text((x, cursor_y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, cursor_y), line or "示", font=font)
        cursor_y += (bbox[3] - bbox[1]) + line_gap
    return cursor_y


def make_slide(title: str, subtitle: str):
    image = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(image)
    rounded_box(draw, (36, 36, CANVAS[0] - 36, CANVAS[1] - 36), fill=PANEL, outline=BORDER, radius=36)
    draw.text((78, 72), title, font=FONT_H1, fill=INK)
    draw.text((82, 136), subtitle, font=FONT_BODY, fill=MUTED)
    rounded_box(draw, (70, 200, 470, 830), fill="#fbf5ec", outline=BORDER, radius=26)
    rounded_box(draw, (500, 200, 1430, 830), fill="#fefcf8", outline=BORDER, radius=26)
    return image, draw


def draw_step_notes(draw: ImageDraw.ImageDraw, header: str, bullets, tip: str, warn: str):
    x0, y0 = 92, 228
    draw.text((x0, y0), header, font=FONT_H2, fill=INK)
    cursor_y = y0 + 54
    for bullet in bullets:
        draw.rounded_rectangle((x0, cursor_y + 10, x0 + 14, cursor_y + 24), radius=7, fill=GREEN)
        cursor_y = draw_multiline(draw, bullet, FONT_BODY, INK, x0 + 28, cursor_y, 320) + 12

    rounded_box(draw, (88, 570, 452, 678), fill=GREEN_SOFT, outline="#b4d7c2", radius=22)
    draw.text((108, 592), "这一步的目标", font=FONT_H3, fill=GREEN)
    draw_multiline(draw, tip, FONT_SMALL, INK, 108, 628, 310, line_gap=6)

    rounded_box(draw, (88, 700, 452, 808), fill=ORANGE_SOFT, outline="#e4c4a7", radius=22)
    draw.text((108, 722), "新手别乱点", font=FONT_H3, fill=ORANGE)
    draw_multiline(draw, warn, FONT_SMALL, INK, 108, 758, 310, line_gap=6)


def draw_phone(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str, body_blocks, footer=None, highlight=None):
    rounded_box(draw, (x, y, x + w, y + h), fill=PHONE, outline="#101214", radius=42)
    rounded_box(draw, (x + 18, y + 18, x + w - 18, y + h - 18), fill="#fbfcfe", outline="#0f1113", radius=34)
    draw.rounded_rectangle((x + w // 2 - 90, y + 26, x + w // 2 + 90, y + 40), radius=7, fill="#0f1113")
    draw.text((x + 42, y + 58), title, font=FONT_H3, fill=INK)
    draw.text((x + w - 140, y + 60), "9:41", font=FONT_SMALL, fill=MUTED)

    cursor_y = y + 110
    for idx, block in enumerate(body_blocks):
        block_h = block.get("height", 88)
        fill = block.get("fill", "#eef2f7")
        outline = block.get("outline", "#d9e1ea")
        if highlight == idx:
            fill = GREEN_SOFT
            outline = "#8ec2a4"
        rounded_box(draw, (x + 34, cursor_y, x + w - 34, cursor_y + block_h), fill=fill, outline=outline, radius=18)
        draw.text((x + 54, cursor_y + 18), block["title"], font=FONT_BODY, fill=INK)
        if block.get("text"):
            draw_multiline(draw, block["text"], FONT_SMALL, MUTED, x + 54, cursor_y + 48, w - 140, line_gap=4)
        cursor_y += block_h + 18

    if footer:
        rounded_box(draw, (x + 34, y + h - 122, x + w - 34, y + h - 56), fill=BLUE, outline=BLUE, radius=18)
        draw.text((x + 64, y + h - 101), footer, font=FONT_BODY, fill="white")


def draw_pi(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, title: str, rows, highlight=None, footer=None, qr=False):
    rounded_box(draw, (x, y, x + size, y + size), fill=PI_CASE, outline="#152437", radius=30)
    screen_x = x + 44
    screen_y = y + 44
    screen_w = size - 88
    rounded_box(draw, (screen_x, screen_y, screen_x + screen_w, screen_y + screen_w), fill="#f9fbff", outline="#152437", radius=16)
    draw.text((screen_x + 24, screen_y + 18), title, font=FONT_H3, fill=INK)

    if qr:
        qr_x = screen_x + 86
        qr_y = screen_y + 88
        qr_size = 220
        draw.rectangle((qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), fill="white", outline=INK, width=4)
        cell = qr_size // 11
        pattern = [
            "11100101111",
            "10010100001",
            "10110111101",
            "00010010000",
            "11101100111",
            "00111011001",
            "10100001011",
            "11011101101",
            "10000100001",
            "11110111011",
            "10100100101",
        ]
        for row_i, row in enumerate(pattern):
            for col_i, bit in enumerate(row):
                if bit == "1":
                    draw.rectangle(
                        (
                            qr_x + col_i * cell + 4,
                            qr_y + row_i * cell + 4,
                            qr_x + (col_i + 1) * cell - 4,
                            qr_y + (row_i + 1) * cell - 4,
                        ),
                        fill=INK,
                    )
        draw.text((screen_x + 74, screen_y + 332), "请让手机持续扫描动画二维码", font=FONT_SMALL, fill=MUTED)
        if footer:
            draw.text((screen_x + 104, screen_y + 368), footer, font=FONT_SMALL, fill=GREEN)
        return

    cursor_y = screen_y + 68
    for idx, row in enumerate(rows):
        fill = BLUE_SOFT
        outline = "#c7d9f2"
        if highlight == idx:
            fill = GREEN_SOFT
            outline = "#8ec2a4"
        rounded_box(draw, (screen_x + 22, cursor_y, screen_x + screen_w - 22, cursor_y + 58), fill=fill, outline=outline, radius=16)
        draw.text((screen_x + 42, cursor_y + 15), row, font=FONT_BODY, fill=INK)
        cursor_y += 76

    if footer:
        rounded_box(
            draw,
            (screen_x + 22, screen_y + screen_w - 86, screen_x + screen_w - 22, screen_y + screen_w - 28),
            fill=ORANGE_SOFT,
            outline="#e4c4a7",
            radius=16,
        )
        draw.text((screen_x + 40, screen_y + screen_w - 66), footer, font=FONT_SMALL, fill=ORANGE)


def draw_review_panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int):
    rounded_box(draw, (x, y, x + w, y + h), fill=PI_CASE, outline="#152437", radius=30)
    rounded_box(draw, (x + 42, y + 42, x + w - 42, y + h - 42), fill="#f9fbff", outline="#152437", radius=16)
    draw.text((x + 74, y + 72), "检查交易", font=FONT_H2, fill=INK)
    card_y = y + 138
    cards = [
        ("转出金额", "0.00010000 BTC"),
        ("矿工费", "158 sat"),
        ("收款地址", "bc1q...demo...t9w"),
    ]
    for title, value in cards:
        rounded_box(draw, (x + 72, card_y, x + w - 72, card_y + 88), fill=BLUE_SOFT, outline="#c7d9f2", radius=18)
        draw.text((x + 96, card_y + 18), title, font=FONT_SMALL, fill=MUTED)
        draw.text((x + 96, card_y + 48), value, font=FONT_BODY, fill=INK)
        card_y += 104

    rounded_box(draw, (x + 72, y + h - 156, x + w - 72, y + h - 96), fill=GREEN, outline=GREEN, radius=18)
    draw.text((x + 110, y + h - 137), "确认签名", font=FONT_BODY, fill="white")
    rounded_box(draw, (x + 72, y + h - 86, x + w - 72, y + h - 36), fill=ORANGE_SOFT, outline="#e4c4a7", radius=18)
    draw.text((x + 110, y + h - 70), "信息不对就返回", font=FONT_SMALL, fill=ORANGE)


def save_slide(name: str, image: Image.Image):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    image.save(path)
    return path


def build_login_slide():
    image, draw = make_slide("步骤 1：第一次开机先设置登录密码", "这一步不是助记词，也不是卡 PIN。它只是这台树莓派自己的开机门锁。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "屏幕标题是“设备登录”。",
            "系统会要求你输入 4 到 12 位数字作为登录密码。",
            "以后每次开机，都先过这一关才会进入主界面。",
        ],
        "先记住这组登录数字，别和卡 PIN、助记词混在一起。",
        "不要把登录密码写成助记词，也不要用生日、手机号这种太好猜的数字。",
    )
    draw_pi(draw, 720, 248, 420, "设备登录", ["请输入新的 4-12 位数字密码", "再次输入以确认"], footer="登录密码只管这台机器")
    draw_phone(
        draw,
        1142,
        246,
        248,
        500,
        "记下来",
        [
            {"title": "这不是助记词", "text": "它只是开机密码。", "height": 118, "fill": ORANGE_SOFT, "outline": "#e4c4a7"},
            {"title": "推荐做法", "text": "单独写在设备说明卡上。", "height": 104},
        ],
    )
    return save_slide("01-login-screen.png", image)


def build_home_slide():
    image, draw = make_slide("步骤 2：看到首页后，先认清 4 个主菜单", "新手最常用的是“扫码签名”和“助记词工具”。先不要急着点智能卡工具。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "标题是“离线签名器”。",
            "首页四个入口分别管签名、助记词、自检和智能卡。",
            "以后大多数日常操作，都是从这个页面进。",
        ],
        "先记住首页结构，后面迷路时回到这里就行。",
        "第一次上手时，智能卡工具和固件自检先不要乱折腾，先把助记词和签名流程走通。",
    )
    draw_pi(
        draw,
        700,
        240,
        520,
        "离线签名器",
        ["扫码签名", "助记词工具", "固件完整性自检", "智能卡工具"],
        highlight=1,
        footer="今天先学会前两项就够了",
    )
    return save_slide("02-home-menu.png", image)


def build_seed_slide():
    image, draw = make_slide("步骤 3：先用“助记词工具”创建或加载助记词", "如果你还没有自己的助记词，就先创建一组 12 词，并且马上做好纸质备份。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "“助记词工具”里会有创建、加载、查看、导出观察钱包等选项。",
            "完全新手推荐先创建 12 词，不要一上来就挑战复杂玩法。",
            "创建完一定要抄下来，再做小额测试。",
        ],
        "把主助记词先安全记下来，后面发交易、导观察钱包都靠它。",
        "没有抄写完成前，不要急着继续下一步，更不要只拍照存在手机里。",
    )
    draw_pi(
        draw,
        700,
        240,
        520,
        "助记词工具",
        ["创建助记词", "加载助记词", "查看已加载助记词", "导出观察钱包"],
        highlight=0,
        footer="创建完成后立刻做纸质备份",
    )
    return save_slide("03-seed-tools.png", image)


def build_wallet_import_slide():
    image, draw = make_slide("步骤 4：把观察钱包导到手机，只看余额、不碰私钥", "推荐先用你自己的安卓观察钱包。它收到树莓派签名结果后，广播体验比官方 BlueWallet 更稳。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "手机上会有“添加 BTC 观察钱包”或类似入口。",
            "把树莓派导出的 xpub / ypub / zpub 扫进手机。",
            "导入成功后，手机只能看余额和发起交易，私钥仍留在树莓派离线端。",
        ],
        "先把“能看余额、能生成待签名二维码”这一步打通。",
        "不要把助记词直接输入联网手机。手机只导观察钱包，不导私钥。",
    )
    draw_phone(
        draw,
        760,
        230,
        380,
        560,
        "添加 BTC 观察钱包",
        [
            {"title": "钱包名称", "text": "我的冷钱包", "height": 86},
            {"title": "导入方式", "text": "扫描 xpub / ypub / zpub", "height": 96},
            {"title": "观察钱包说明", "text": "只能看余额和发起交易。", "height": 116, "fill": BLUE_SOFT},
        ],
        footer="继续",
    )
    draw_pi(
        draw,
        1160,
        270,
        230,
        "树莓派导出",
        ["xpub", "ypub", "zpub"],
        highlight=2,
    )
    return save_slide("04-watch-wallet-import.png", image)


def build_send_slide():
    image, draw = make_slide("步骤 5：在手机发起一笔很小的测试交易", "第一次只发很小金额，确认地址、金额、手续费、扫描回传都没问题，再考虑正式使用。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "手机里填写收款地址、金额和网络费。",
            "确认后，手机会生成一组待签名二维码。",
            "这时手机还不能花钱，必须交给树莓派离线签名。",
        ],
        "先做一笔小额测试，验证全流程和自己手写备份都没问题。",
        "第一次不要发大额，也不要在没看懂收款地址时盲点下一步。",
    )
    draw_phone(
        draw,
        860,
        220,
        420,
        580,
        "发送 BTC",
        [
            {"title": "收款地址", "text": "bc1q...demo...t9w", "height": 96},
            {"title": "金额", "text": "0.00010000 BTC", "height": 86},
            {"title": "矿工费", "text": "158 sat", "height": 86},
            {"title": "下一步会生成待签名二维码", "text": "让树莓派来扫。", "height": 110, "fill": BLUE_SOFT},
        ],
        footer="生成待签名二维码",
    )
    return save_slide("05-send-btc.png", image)


def build_scan_slide():
    image, draw = make_slide("步骤 6：树莓派点“扫码签名”，对准手机二维码", "树莓派只负责检查和签名。只要你不把助记词输到手机，私钥就还在离线端。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "树莓派首页点“扫码签名”。",
            "摄像头页面会提示把手机二维码对准镜头。",
            "扫码完成后，树莓派会进入交易检查页面。",
        ],
        "把手机亮度调高一点，二维码保持居中，别让镜头离得太远。",
        "如果识别慢，不要连续乱按返回；先稳住手机二维码，让它扫完一轮。",
    )
    draw_pi(
        draw,
        750,
        240,
        520,
        "扫描待签名二维码",
        ["把手机二维码对准摄像头", "保持手机亮度足够", "系统会自动进入下一页"],
        highlight=0,
        footer="识别完成后会自动跳转",
    )
    return save_slide("06-scan-sign.png", image)


def build_review_slide():
    image, draw = make_slide("步骤 7：在树莓派上逐项检查，再决定是否签名", "真正该紧张的是这一步。金额、地址、手续费不对，就立刻返回，不要硬签。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "树莓派会列出金额、手续费、收款地址等关键信息。",
            "你确认都对，才按“确认签名”。",
            "一旦签名完成，手机拿到结果后就能广播。",
        ],
        "把金额和地址跟你原本想发的内容核对一遍，这是冷签最重要的检查动作。",
        "看不懂就不要签。宁可回去重来，也别赌自己“应该没问题”。",
    )
    draw_review_panel(draw, 780, 236, 560, 560)
    return save_slide("07-review-transaction.png", image)


def build_signed_qr_slide():
    image, draw = make_slide("步骤 8：签名完成后，树莓派会显示已签名结果二维码", "这时手机需要反过来扫描树莓派。对手机来说，这才是最终可以广播的签名结果。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "树莓派屏幕上出现已签名结果二维码。",
            "有些结果会是动画二维码，手机要持续扫完。",
            "扫回手机后，手机才会出现“广播交易”入口。",
        ],
        "保持树莓派和手机都别乱动，让手机一次扫完整组二维码。",
        "如果手机扫回后看见一大段文字，不要慌，先按教程里的广播方式继续。",
    )
    draw_pi(draw, 810, 236, 520, "已签名结果", [], footer="扫描完成后回到手机广播", qr=True)
    return save_slide("08-signed-qr.png", image)


def build_broadcast_slide():
    image, draw = make_slide("步骤 9：手机扫回后广播，第一笔测试就完成了", "如果你用的是自家安卓观察钱包，体验会更顺。官方 BlueWallet 仍然可能遇到长页面不方便点广播。")
    draw_step_notes(
        draw,
        "你会看到什么",
        [
            "手机显示“已收到签名结果”或类似提示。",
            "确认交易摘要后，点“广播交易”。",
            "广播成功后，就可以用 txid 到区块浏览器查询状态。",
        ],
        "第一次只要成功发出一笔小额交易，就说明你的固件、手机钱包、扫码链路都走通了。",
        "如果是官方 BlueWallet 遇到长页面，优先用“复制并稍后广播”或换自家观察钱包。",
    )
    draw_phone(
        draw,
        860,
        220,
        420,
        580,
        "广播交易",
        [
            {"title": "交易已签名", "text": "输入数: 4    手续费: 158 sat", "height": 106, "fill": GREEN_SOFT, "outline": "#8ec2a4"},
            {"title": "txid", "text": "5e33dc47...06598fd", "height": 98},
            {"title": "如果是 BlueWallet", "text": "页面太长时可复制 raw tx 到广播页。", "height": 116, "fill": ORANGE_SOFT, "outline": "#e4c4a7"},
        ],
        footer="广播交易",
    )
    return save_slide("09-broadcast.png", image)


def build_bluewallet_note_slide():
    image, draw = make_slide("补充：官方 BlueWallet 这条路能用，但不一定最省心", "它已经能扫回树莓派的签名结果，但在小屏手机上，长交易有时会把底部广播按钮挤到屏幕外。")
    draw_step_notes(
        draw,
        "遇到这种情况怎么做",
        [
            "先点“复制并稍后广播”。",
            "把 raw tx hex 粘到 mempool.space 或 Blockstream 的广播页。",
            "或者直接改走自家安卓观察钱包这条更稳的路径。",
        ],
        "先把交易广播成功，不要被 BlueWallet 这个页面卡住整条流程。",
        "多半是 BlueWallet 自己的广播页太挤，不是树莓派签名错了。",
    )
    draw_phone(
        draw,
        860,
        220,
        420,
        580,
        "发送",
        [
            {"title": "这是一笔已签名交易", "text": "下面是一大段 tx hex。", "height": 106},
            {"title": "复制并稍后广播", "text": "先复制，再去广播页粘贴。", "height": 110, "fill": GREEN_SOFT, "outline": "#8ec2a4"},
            {"title": "别误会", "text": "能看到这页，说明树莓派签名基本已经成功回传。", "height": 120, "fill": BLUE_SOFT},
        ],
    )
    return save_slide("10-bluewallet-note.png", image)


def main():
    outputs = [
        build_login_slide(),
        build_home_slide(),
        build_seed_slide(),
        build_wallet_import_slide(),
        build_send_slide(),
        build_scan_slide(),
        build_review_slide(),
        build_signed_qr_slide(),
        build_broadcast_slide(),
        build_bluewallet_note_slide(),
    ]
    for output in outputs:
        print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
