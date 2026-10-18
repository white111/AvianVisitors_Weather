<?php
// AvianVisitors - latest ThermoPro TX-2 readings for the collage weather badge.
// Written by avian/thermopro/thermopro_rx.py (service avian-thermopro).
// Read-only and public like the collage itself: room/outdoor temperature only.

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');

const THERMOPRO_FILE = '/var/lib/avian-thermopro/latest.json';
const THERMOPRO_MAX_BYTES = 16384;

function thermopro_respond(array $body): void {
    echo json_encode($body, JSON_UNESCAPED_SLASHES);
    exit;
}

$now = time();
$empty = ['ok' => true, 'now' => $now, 'units' => 'F', 'sensors' => []];

if (!is_file(THERMOPRO_FILE) || !is_readable(THERMOPRO_FILE)) {
    thermopro_respond($empty + ['note' => 'no readings yet']);
}
$size = filesize(THERMOPRO_FILE);
if ($size === false || $size > THERMOPRO_MAX_BYTES) {
    thermopro_respond($empty + ['note' => 'readings file unavailable']);
}
$data = json_decode((string) file_get_contents(THERMOPRO_FILE), true);
if (!is_array($data)) {
    thermopro_respond($empty + ['note' => 'readings file unreadable']);
}

$units = (($data['units'] ?? 'F') === 'C') ? 'C' : 'F';
$sensors = [];
foreach (array_slice((array) ($data['sensors'] ?? []), 0, 3) as $sensor) {
    if (!is_array($sensor) || !is_numeric($sensor['temp_c'] ?? null)) continue;
    $channel = (int) ($sensor['channel'] ?? 0);
    if ($channel < 1 || $channel > 3) continue;
    $seen = (int) ($sensor['seen'] ?? 0);
    $humidity = $sensor['humidity'] ?? null;
    $sensors[] = [
        'channel' => $channel,
        'label' => substr((string) ($sensor['label'] ?? ('Channel ' . $channel)), 0, 24),
        'temp_c' => round((float) $sensor['temp_c'], 1),
        'humidity' => is_numeric($humidity) ? (int) $humidity : null,
        'age_s' => max(0, $now - $seen),
    ];
}

thermopro_respond(['ok' => true, 'now' => $now, 'units' => $units, 'sensors' => $sensors]);
