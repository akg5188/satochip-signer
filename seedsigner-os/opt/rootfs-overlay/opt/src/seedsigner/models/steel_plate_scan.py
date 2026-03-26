from __future__ import annotations

from math import atan2, cos, sin, sqrt

from PIL import Image, ImageOps


CARD_WIDTH_MM = 85.6
CARD_HEIGHT_MM = 54.0
CARD_ASPECT = CARD_WIDTH_MM / CARD_HEIGHT_MM
CARD_PADDING_X_MM = 2.4
CARD_PADDING_Y_MM = 3.2
COLUMN_GAP_MM = 1.4
ROW_GAP_MM = 1.25
LABEL_WIDTH_MM = 6.0
CIRCLE_SIZE_MM = 2.7
CIRCLE_GAP_MM = 0.25
ROWS_PER_COLUMN = 6
MARKER_SIZE_MM = 2.0
MARKER_OFFSET_X_MM = 0.2
MARKER_OFFSET_Y_MM = 0.2
WEIGHTS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def _percentile_from_histogram(histogram: list[int], percentile: float) -> int:
    total = sum(histogram)
    if total <= 0:
        return 0
    target = total * percentile
    seen = 0
    for index, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return index
    return len(histogram) - 1


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    padding_ratio: float = 0.03,
) -> tuple[int, int, int, int]:
    pad_x = int((bbox[2] - bbox[0]) * padding_ratio)
    pad_y = int((bbox[3] - bbox[1]) * padding_ratio)
    return (
        max(0, bbox[0] - pad_x),
        max(0, bbox[1] - pad_y),
        min(image_width, bbox[2] + pad_x),
        min(image_height, bbox[3] + pad_y),
    )


def _fit_bbox_to_aspect(
    bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    aspect = width / height

    if aspect > CARD_ASPECT:
        width = int(height * CARD_ASPECT)
    else:
        height = int(width / CARD_ASPECT)

    left = max(0, int(round(center_x - width / 2)))
    top = max(0, int(round(center_y - height / 2)))
    right = min(image_width, left + width)
    bottom = min(image_height, top + height)
    left = max(0, right - width)
    top = max(0, bottom - height)
    return (left, top, right, bottom)


def _center_crop_bbox(image_width: int, image_height: int) -> tuple[int, int, int, int]:
    usable_width = int(image_width * 0.84)
    usable_height = int(usable_width / CARD_ASPECT)
    if usable_height > int(image_height * 0.84):
        usable_height = int(image_height * 0.84)
        usable_width = int(usable_height * CARD_ASPECT)
    left = (image_width - usable_width) // 2
    top = (image_height - usable_height) // 2
    return (left, top, left + usable_width, top + usable_height)


def _candidate_score(
    bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
) -> float:
    area_ratio = _bbox_area(bbox) / max(1, image_width * image_height)
    if area_ratio < 0.08 or area_ratio > 0.95:
        return -1.0
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    aspect = width / height
    aspect_delta = abs(aspect - CARD_ASPECT) / CARD_ASPECT
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    offset = abs(center_x - image_width / 2) / image_width + abs(center_y - image_height / 2) / image_height
    return area_ratio * 2.0 + (1.0 - min(aspect_delta, 1.0)) - offset


def _find_projection_bbox(gray: Image.Image) -> tuple[int, int, int, int] | None:
    width, height = gray.size
    if width <= 0 or height <= 0:
        return None

    scale = 1.0
    sample = gray
    target_width = 420
    if width > target_width:
        scale = width / target_width
        sample = gray.resize((target_width, max(1, int(round(height / scale)))), Image.Resampling.BILINEAR)

    sample_width, sample_height = sample.size
    histogram = sample.histogram()
    thresholds = [
        max(170, _percentile_from_histogram(histogram, percentile))
        for percentile in (0.90, 0.87, 0.84)
    ]

    candidates: list[tuple[int, int, int, int]] = []
    for threshold in thresholds:
        col_counts = [0] * sample_width
        row_counts = [0] * sample_height
        for y in range(sample_height):
            for x in range(sample_width):
                if sample.getpixel((x, y)) >= threshold:
                    col_counts[x] += 1
                    row_counts[y] += 1

        if not col_counts or not row_counts:
            continue

        max_col = max(col_counts)
        max_row = max(row_counts)
        if max_col <= 0 or max_row <= 0:
            continue

        col_gate = max(4, int(max_col * 0.25))
        row_gate = max(4, int(max_row * 0.25))
        xs = [index for index, count in enumerate(col_counts) if count >= col_gate]
        ys = [index for index, count in enumerate(row_counts) if count >= row_gate]
        if not xs or not ys:
            continue

        bbox = (
            int(xs[0] * scale),
            int(ys[0] * scale),
            min(width, int((xs[-1] + 1) * scale)),
            min(height, int((ys[-1] + 1) * scale)),
        )
        candidates.append(_expand_bbox(bbox, width, height, padding_ratio=0.01))

    if not candidates:
        return None

    best = max(candidates, key=lambda bbox: _candidate_score(bbox, width, height))
    if _candidate_score(best, width, height) < 0:
        return None
    return _fit_bbox_to_aspect(best, width, height)


def _bright_threshold_candidates(gray: Image.Image) -> list[int]:
    histogram = gray.histogram()
    return [
        max(170, _percentile_from_histogram(histogram, percentile))
        for percentile in (0.90, 0.87, 0.84)
    ]


def _sample_bright_points(gray: Image.Image, threshold: int) -> tuple[float, list[tuple[float, float]]]:
    width, height = gray.size
    scale = 1.0
    sample = gray
    target_width = 420
    if width > target_width:
        scale = width / target_width
        sample = gray.resize((target_width, max(1, int(round(height / scale)))), Image.Resampling.BILINEAR)

    points: list[tuple[float, float]] = []
    for y in range(sample.height):
        for x in range(sample.width):
            if sample.getpixel((x, y)) >= threshold:
                points.append(((x + 0.5) * scale, (y + 0.5) * scale))
    return scale, points


def _order_frame_corners(corners: list[tuple[float, float]]) -> dict[str, tuple[float, float]]:
    ordered_by_y = sorted(corners, key=lambda point: (point[1], point[0]))
    top = sorted(ordered_by_y[:2], key=lambda point: point[0])
    bottom = sorted(ordered_by_y[2:], key=lambda point: point[0])
    return {
        "tl": top[0],
        "tr": top[1],
        "bl": bottom[0],
        "br": bottom[1],
    }


def _find_card_frame(gray: Image.Image) -> dict[str, tuple[float, float]] | None:
    width, height = gray.size
    for threshold in _bright_threshold_candidates(gray):
        _, points = _sample_bright_points(gray, threshold)
        if len(points) < 200:
            continue

        total = float(len(points))
        mean_x = sum(point[0] for point in points) / total
        mean_y = sum(point[1] for point in points) / total

        cov_xx = sum((point[0] - mean_x) ** 2 for point in points) / total
        cov_yy = sum((point[1] - mean_y) ** 2 for point in points) / total
        cov_xy = sum((point[0] - mean_x) * (point[1] - mean_y) for point in points) / total

        angle = 0.5 * atan2(2.0 * cov_xy, cov_xx - cov_yy)
        ux, uy = cos(angle), sin(angle)
        vx, vy = -uy, ux

        projections_u = []
        projections_v = []
        for point_x, point_y in points:
            dx = point_x - mean_x
            dy = point_y - mean_y
            projections_u.append(dx * ux + dy * uy)
            projections_v.append(dx * vx + dy * vy)

        min_u = min(projections_u)
        max_u = max(projections_u)
        min_v = min(projections_v)
        max_v = max(projections_v)

        frame_corners = [
            (mean_x + min_u * ux + min_v * vx, mean_y + min_u * uy + min_v * vy),
            (mean_x + max_u * ux + min_v * vx, mean_y + max_u * uy + min_v * vy),
            (mean_x + min_u * ux + max_v * vx, mean_y + min_u * uy + max_v * vy),
            (mean_x + max_u * ux + max_v * vx, mean_y + max_u * uy + max_v * vy),
        ]
        ordered = _order_frame_corners(frame_corners)
        top_width = sqrt((ordered["tr"][0] - ordered["tl"][0]) ** 2 + (ordered["tr"][1] - ordered["tl"][1]) ** 2)
        left_height = sqrt((ordered["bl"][0] - ordered["tl"][0]) ** 2 + (ordered["bl"][1] - ordered["tl"][1]) ** 2)
        if top_width < width * 0.35 or left_height < height * 0.25:
            continue
        return ordered
    return None


def _find_card_bbox(gray: Image.Image) -> tuple[int, int, int, int]:
    width, height = gray.size
    histogram = gray.histogram()
    projection_bbox = _find_projection_bbox(gray)
    if projection_bbox:
        return projection_bbox

    candidates: list[tuple[int, int, int, int]] = []

    for percentile in (0.86, 0.82, 0.78, 0.74):
        threshold = _percentile_from_histogram(histogram, percentile)
        mask = gray.point(lambda px, t=threshold: 255 if px >= t else 0)
        bbox = mask.getbbox()
        if bbox:
            candidates.append(_expand_bbox(bbox, width, height))

    for percentile in (0.14, 0.18, 0.22, 0.26):
        threshold = _percentile_from_histogram(histogram, percentile)
        mask = gray.point(lambda px, t=threshold: 255 if px <= t else 0)
        bbox = mask.getbbox()
        if bbox:
            candidates.append(_expand_bbox(bbox, width, height))

    if not candidates:
        return _center_crop_bbox(width, height)

    best = max(candidates, key=lambda bbox: _candidate_score(bbox, width, height))
    if _candidate_score(best, width, height) < 0:
        return _center_crop_bbox(width, height)
    return _fit_bbox_to_aspect(best, width, height)


def _sample_circle_brightness(gray: Image.Image, center_x: float, center_y: float, radius: float) -> float:
    left = max(0, int(center_x - radius))
    top = max(0, int(center_y - radius))
    right = min(gray.width, int(center_x + radius) + 1)
    bottom = min(gray.height, int(center_y + radius) + 1)
    radius_sq = radius * radius

    total = 0
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            dx = (x + 0.5) - center_x
            dy = (y + 0.5) - center_y
            if dx * dx + dy * dy <= radius_sq:
                total += gray.getpixel((x, y))
                count += 1
    return total / max(1, count)


def _marker_center_mm(position: str) -> tuple[float, float]:
    center_x = MARKER_OFFSET_X_MM + MARKER_SIZE_MM / 2.0
    center_y = MARKER_OFFSET_Y_MM + MARKER_SIZE_MM / 2.0
    if position == "tl":
        return center_x, center_y
    if position == "tr":
        return CARD_WIDTH_MM - center_x, center_y
    if position == "bl":
        return center_x, CARD_HEIGHT_MM - center_y
    if position == "br":
        return CARD_WIDTH_MM - center_x, CARD_HEIGHT_MM - center_y
    raise ValueError(f"未知角点: {position}")


def _otsu_threshold(values: list[int]) -> int:
    histogram = [0] * 256
    for value in values:
        histogram[max(0, min(255, int(round(value))))] += 1

    total = sum(histogram)
    if total <= 0:
        return 127

    sum_total = sum(index * count for index, count in enumerate(histogram))
    sum_background = 0.0
    weight_background = 0
    max_variance = -1.0
    threshold = 127

    for index, count in enumerate(histogram):
        weight_background += count
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break

        sum_background += index * count
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        between = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if between > max_variance:
            max_variance = between
            threshold = index
    return threshold


def _detect_marker_center(
    gray: Image.Image,
    expected_x: float,
    expected_y: float,
    radius_x: float,
    radius_y: float,
) -> tuple[float, float] | None:
    left = max(0, int(expected_x - radius_x))
    top = max(0, int(expected_y - radius_y))
    right = min(gray.width, int(expected_x + radius_x) + 1)
    bottom = min(gray.height, int(expected_y + radius_y) + 1)
    if right - left < 4 or bottom - top < 4:
        return None

    values: list[int] = []
    pixels: list[tuple[int, int, int]] = []
    for y in range(top, bottom):
        for x in range(left, right):
            value = gray.getpixel((x, y))
            values.append(value)
            pixels.append((x, y, value))

    if not values:
        return None

    min_value = min(values)
    max_value = max(values)
    contrast = max_value - min_value
    if contrast < 18:
        return None

    threshold = min(
        _otsu_threshold(values),
        int(min_value + contrast * 0.38),
    )
    threshold = max(min_value + 4, min(threshold, max_value - 4))

    weighted_x = 0.0
    weighted_y = 0.0
    total_weight = 0.0
    dark_count = 0
    max_radius_sq = max(radius_x * radius_x, radius_y * radius_y)

    for x, y, value in pixels:
        if value > threshold:
            continue
        dx = ((x + 0.5) - expected_x) / max(1.0, radius_x)
        dy = ((y + 0.5) - expected_y) / max(1.0, radius_y)
        dist_sq = dx * dx + dy * dy
        if dist_sq > 1.2:
            continue
        spatial_weight = max(0.18, 1.0 - dist_sq / 1.2)
        darkness_weight = (threshold - value + 1)
        weight = darkness_weight * spatial_weight
        weighted_x += (x + 0.5) * weight
        weighted_y += (y + 0.5) * weight
        total_weight += weight
        dark_count += 1

    if dark_count < 10 or total_weight < max(20.0, max_radius_sq * 0.18):
        return None
    return (weighted_x / total_weight, weighted_y / total_weight)


def _frame_edge_metrics(frame: dict[str, tuple[float, float]]) -> tuple[float, float]:
    top_width = sqrt((frame["tr"][0] - frame["tl"][0]) ** 2 + (frame["tr"][1] - frame["tl"][1]) ** 2)
    left_height = sqrt((frame["bl"][0] - frame["tl"][0]) ** 2 + (frame["bl"][1] - frame["tl"][1]) ** 2)
    return top_width / CARD_WIDTH_MM, left_height / CARD_HEIGHT_MM


def _project_from_frame(
    x_mm: float,
    y_mm: float,
    frame: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    u = x_mm / CARD_WIDTH_MM
    v = y_mm / CARD_HEIGHT_MM
    tl = frame["tl"]
    tr = frame["tr"]
    bl = frame["bl"]
    br = frame["br"]
    x = (
        tl[0] * (1 - u) * (1 - v)
        + tr[0] * u * (1 - v)
        + bl[0] * (1 - u) * v
        + br[0] * u * v
    )
    y = (
        tl[1] * (1 - u) * (1 - v)
        + tr[1] * u * (1 - v)
        + bl[1] * (1 - u) * v
        + br[1] * u * v
    )
    return x, y


def _find_card_markers(
    gray: Image.Image,
    frame: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]] | None:
    mm_to_x, mm_to_y = _frame_edge_metrics(frame)
    search_radius_x = max(10.0, mm_to_x * 5.5)
    search_radius_y = max(10.0, mm_to_y * 5.5)
    markers: dict[str, tuple[float, float]] = {}

    for position in ("tl", "tr", "bl", "br"):
        marker_mm_x, marker_mm_y = _marker_center_mm(position)
        expected_x, expected_y = _project_from_frame(marker_mm_x, marker_mm_y, frame)
        center = _detect_marker_center(
            gray,
            expected_x=expected_x,
            expected_y=expected_y,
            radius_x=search_radius_x,
            radius_y=search_radius_y,
        )
        if center is None:
            return None
        markers[position] = center

    return markers


def _circle_centers(bbox: tuple[int, int, int, int]) -> list[tuple[int, int, float, float, float]]:
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    inner_width_mm = CARD_WIDTH_MM - 2 * CARD_PADDING_X_MM
    column_width_mm = (inner_width_mm - COLUMN_GAP_MM) / 2
    row_height_mm = (CARD_HEIGHT_MM - 2 * CARD_PADDING_Y_MM - ROW_GAP_MM * (ROWS_PER_COLUMN - 1)) / ROWS_PER_COLUMN
    mm_to_x = width / CARD_WIDTH_MM
    mm_to_y = height / CARD_HEIGHT_MM
    circle_radius_px = max(1.5, min(mm_to_x, mm_to_y) * (CIRCLE_SIZE_MM / 2.0) * 0.6)

    centers: list[tuple[int, int, float, float, float]] = []
    for column in range(2):
        column_left_mm = CARD_PADDING_X_MM + column * (column_width_mm + COLUMN_GAP_MM)
        circles_left_mm = column_left_mm + LABEL_WIDTH_MM
        for row in range(ROWS_PER_COLUMN):
            word_index = row + column * ROWS_PER_COLUMN
            row_top_mm = CARD_PADDING_Y_MM + row * (row_height_mm + ROW_GAP_MM)
            center_y = top + (row_top_mm + row_height_mm / 2.0) * mm_to_y
            for circle_index, weight in enumerate(WEIGHTS):
                center_x = left + (
                    circles_left_mm
                    + circle_index * (CIRCLE_SIZE_MM + CIRCLE_GAP_MM)
                    + CIRCLE_SIZE_MM / 2.0
                ) * mm_to_x
                centers.append((word_index, weight, center_x, center_y, circle_radius_px))
    return centers


def _circle_centers_from_frame(
    frame: dict[str, tuple[float, float]],
) -> list[tuple[int, int, float, float, float]]:
    mm_to_x, mm_to_y = _frame_edge_metrics(frame)
    inner_width_mm = CARD_WIDTH_MM - 2 * CARD_PADDING_X_MM
    column_width_mm = (inner_width_mm - COLUMN_GAP_MM) / 2
    row_height_mm = (CARD_HEIGHT_MM - 2 * CARD_PADDING_Y_MM - ROW_GAP_MM * (ROWS_PER_COLUMN - 1)) / ROWS_PER_COLUMN
    circle_radius_px = max(1.5, min(mm_to_x, mm_to_y) * (CIRCLE_SIZE_MM / 2.0) * 0.58)

    centers: list[tuple[int, int, float, float, float]] = []
    for column in range(2):
        column_left_mm = CARD_PADDING_X_MM + column * (column_width_mm + COLUMN_GAP_MM)
        circles_left_mm = column_left_mm + LABEL_WIDTH_MM
        for row in range(ROWS_PER_COLUMN):
            word_index = row + column * ROWS_PER_COLUMN
            row_top_mm = CARD_PADDING_Y_MM + row * (row_height_mm + ROW_GAP_MM)
            center_y_mm = row_top_mm + row_height_mm / 2.0
            for weight_index, weight in enumerate(WEIGHTS):
                center_x_mm = (
                    circles_left_mm
                    + weight_index * (CIRCLE_SIZE_MM + CIRCLE_GAP_MM)
                    + CIRCLE_SIZE_MM / 2.0
                )
                center_x, center_y = _project_from_frame(center_x_mm, center_y_mm, frame)
                centers.append((word_index, weight, center_x, center_y, circle_radius_px))
    return centers


def _project_from_markers(
    x_mm: float,
    y_mm: float,
    markers: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    left_marker_x, top_marker_y = _marker_center_mm("tl")
    right_marker_x, _ = _marker_center_mm("tr")
    _, bottom_marker_y = _marker_center_mm("bl")

    u = (x_mm - left_marker_x) / max(1e-9, right_marker_x - left_marker_x)
    v = (y_mm - top_marker_y) / max(1e-9, bottom_marker_y - top_marker_y)

    tl = markers["tl"]
    tr = markers["tr"]
    bl = markers["bl"]
    br = markers["br"]

    x = (
        tl[0] * (1 - u) * (1 - v)
        + tr[0] * u * (1 - v)
        + bl[0] * (1 - u) * v
        + br[0] * u * v
    )
    y = (
        tl[1] * (1 - u) * (1 - v)
        + tr[1] * u * (1 - v)
        + bl[1] * (1 - u) * v
        + br[1] * u * v
    )
    return x, y


def _circle_centers_from_markers(
    bbox: tuple[int, int, int, int],
    markers: dict[str, tuple[float, float]],
) -> list[tuple[int, int, float, float, float]]:
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    inner_width_mm = CARD_WIDTH_MM - 2 * CARD_PADDING_X_MM
    column_width_mm = (inner_width_mm - COLUMN_GAP_MM) / 2
    row_height_mm = (CARD_HEIGHT_MM - 2 * CARD_PADDING_Y_MM - ROW_GAP_MM * (ROWS_PER_COLUMN - 1)) / ROWS_PER_COLUMN
    mm_to_x = width / CARD_WIDTH_MM
    mm_to_y = height / CARD_HEIGHT_MM
    circle_radius_px = max(1.5, min(mm_to_x, mm_to_y) * (CIRCLE_SIZE_MM / 2.0) * 0.58)

    centers: list[tuple[int, int, float, float, float]] = []
    for column in range(2):
        column_left_mm = CARD_PADDING_X_MM + column * (column_width_mm + COLUMN_GAP_MM)
        circles_left_mm = column_left_mm + LABEL_WIDTH_MM
        for row in range(ROWS_PER_COLUMN):
            word_index = row + column * ROWS_PER_COLUMN
            row_top_mm = CARD_PADDING_Y_MM + row * (row_height_mm + ROW_GAP_MM)
            center_y_mm = row_top_mm + row_height_mm / 2.0
            for weight_index, weight in enumerate(WEIGHTS):
                center_x_mm = (
                    circles_left_mm
                    + weight_index * (CIRCLE_SIZE_MM + CIRCLE_GAP_MM)
                    + CIRCLE_SIZE_MM / 2.0
                )
                center_x, center_y = _project_from_markers(center_x_mm, center_y_mm, markers)
                centers.append((word_index, weight, center_x, center_y, circle_radius_px))
    return centers


def recognize_plate_groups_from_image(image: Image.Image) -> list[str]:
    gray = ImageOps.autocontrast(ImageOps.exif_transpose(image).convert("L"), cutoff=2)
    frame = _find_card_frame(gray)
    bbox = _find_card_bbox(gray)
    markers = _find_card_markers(gray, frame) if frame else None
    if markers:
        centers = _circle_centers_from_markers(bbox, markers)
    elif frame:
        centers = _circle_centers_from_frame(frame)
    else:
        centers = _circle_centers(bbox)

    samples: list[tuple[int, int, float]] = []
    values: list[int] = []
    for word_index, weight, center_x, center_y, radius in centers:
        brightness = _sample_circle_brightness(gray, center_x, center_y, radius)
        samples.append((word_index, weight, brightness))
        values.append(int(round(brightness)))

    if not values:
        raise ValueError("没有识别到钢板点位，请重试。")

    contrast = max(values) - min(values)
    if contrast < 12:
        raise ValueError("画面对比度不足，请将钢板/纸张放在深色背景上并靠近拍摄。")

    grouped: list[list[int]] = [[] for _ in range(12)]
    grouped_samples: list[list[tuple[int, float]]] = [[] for _ in range(12)]
    for word_index, weight, brightness in samples:
        grouped_samples[word_index].append((weight, brightness))

    for word_index, row_samples in enumerate(grouped_samples):
        if not row_samples:
            continue
        row_values = [brightness for _, brightness in row_samples]
        row_min = min(row_values)
        row_max = max(row_values)
        row_contrast = row_max - row_min
        if row_contrast < 16:
            continue
        row_threshold = row_max - max(18.0, row_contrast * 0.34)
        for weight, brightness in row_samples:
            if brightness <= row_threshold:
                grouped[word_index].append(weight)

    return [" ".join(str(weight) for weight in groups) or "0" for groups in grouped]
