// Parametric tray for the white card reader mounted above the Open Pill case.
// Edit the parameters below to match your measured reader size.

$fn = 48;

reader_len = 46;
reader_w = 18;
reader_h = 8;

clearance = 0.4;
base_th = 2.4;
wall_th = 2.0;
wall_h = 6.0;
back_stop_th = 2.0;

strap_slot_w = 4.0;
strap_slot_len = 12.0;
strap_edge_margin = 5.0;

cable_slot_w = 8.0;
cable_slot_len = 12.0;

mount_pad_len = reader_len + 10;
mount_pad_w = reader_w + 10;

inner_len = reader_len + clearance * 2;
inner_w = reader_w + clearance * 2;

outer_len = inner_len + wall_th * 2;
outer_w = inner_w + wall_th * 2;

module tray_body() {
    union() {
        cube([outer_len, outer_w, base_th]);

        translate([0, 0, base_th])
            cube([outer_len, wall_th, wall_h]);

        translate([0, outer_w - wall_th, base_th])
            cube([outer_len, wall_th, wall_h]);

        translate([outer_len - back_stop_th, wall_th, base_th])
            cube([back_stop_th, inner_w, wall_h]);
    }
}

module strap_slots() {
    for (x = [strap_edge_margin, outer_len - strap_edge_margin - strap_slot_len]) {
        translate([x, -0.1, base_th / 2])
            cube([strap_slot_len, outer_w + 0.2, base_th + 0.2], center = true);
    }
}

module cable_slot() {
    translate([-0.1, (outer_w - cable_slot_w) / 2, -0.1])
        cube([cable_slot_len + 0.1, cable_slot_w, base_th + wall_h + 0.2]);
}

difference() {
    tray_body();
    strap_slots();
    cable_slot();
}
