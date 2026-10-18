<?php
// AvianVisitors - latest 433 MHz sensor readings (ThermoPro TX-2, AcuRite
// 592TXR) for the collage weather badge.
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
foreach (array_slice((array) ($data['sensors'] ?? []), 0, 6) as $sensor) {
    if (!is_array($sensor) || !is_numeric($sensor['temp_c'] ?? null)) continue;
    // ThermoPro channels are 1-3, AcuRite channels A-C.
    $channel = strtoupper((string) ($sensor['channel'] ?? ''));
    if (!in_array($channel, ['1', '2', '3', 'A', 'B', 'C'], true)) continue;
    $seen = (int) ($sensor['seen'] ?? 0);
    $humidity = $sensor['humidity'] ?? null;
    $sensors[] = [
        'source' => (($sensor['source'] ?? '') === 'acurite') ? 'acurite' : 'thermopro',
        'channel' => $channel,
        'label' => substr((string) ($sensor['label'] ?? ('Channel ' . $channel)), 0, 24),
        'temp_c' => round((float) $sensor['temp_c'], 1),
        'humidity' => is_numeric($humidity) ? (int) $humidity : null,
        'age_s' => max(0, $now - $seen),
    ];
}

thermopro_respond(['ok' => true, 'now' => $now, 'units' => $units, 'sensors' => $sensors]);
