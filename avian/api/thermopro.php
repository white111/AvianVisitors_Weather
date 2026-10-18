<?php
// AvianVisitors - weather sensor readings (ThermoPro TX-2 and AcuRite 592TXR
// on the 433 MHz RXB6, La Crosse IT+ TX29/TX35 on an RTL-SDR at 915 MHz) for
// the collage weather badge, plus the names set in Settings.
//
// Readings are written by avian/thermopro/thermopro_rx.py (service
// avian-thermopro). Names and show/hide choices made in Settings > Weather
// sensors live in /var/lib/avian-forecast/sensors.json (caddy-writable) and
// override the service's --label defaults.
//
//   GET                  public: fresh readings for sensors that are shown
//   GET  ?action=config  admin: every sensor heard or named, with its settings
//   POST {action: ...}   admin + X-Avian-Action JSON:
//        name   {key, name}     set a display name ("" restores the default)
//        hide   {key, hidden}   hide a sensor from the collage, or show it
//        forget {key}           drop a sensor's saved name and setting

declare(strict_types=1);

require_once __DIR__ . '/admin-auth.php';

const SENSORS_MAX_BYTES = 16384;
const SENSORS_MAX = 16;
const SENSORS_SETUP_HINT = 'run avian/thermopro/install.sh on the Pi to enable sensor settings';

function sensors_respond(int $status, array $body): void {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function sensors_cli_env(string $name, string $default): string {
    // CLI-only overrides keep tests away from the real station state.
    if (PHP_SAPI === 'cli') {
        $value = getenv($name);
        if (is_string($value) && $value !== '') return $value;
    }
    return $default;
}

function sensors_readings_path(): string {
    return sensors_cli_env('AV_THERMOPRO_FILE', '/var/lib/avian-thermopro/latest.json');
}

function sensors_settings_dir(): string {
    return rtrim(sensors_cli_env('AV_FORECAST_DIR', '/var/lib/avian-forecast'), '/');
}

function sensors_read_json(string $path): ?array {
    if (!is_file($path) || is_link($path) || !is_readable($path)) return null;
    $size = filesize($path);
    if ($size === false || $size > SENSORS_MAX_BYTES) return null;
    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : null;
}

function sensors_clean_name(mixed $value): string {
    $text = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', is_scalar($value) ? (string) $value : '');
    $text = trim((string) preg_replace('/\s+/u', ' ', (string) $text));
    return function_exists('mb_substr') ? mb_substr($text, 0, 24) : substr($text, 0, 24);
}

function sensors_valid_key(mixed $value): ?string {
    $key = is_string($value) ? $value : '';
    return preg_match('/^(thermopro-[123]|acurite-[ABC]|lacrosse-\d{1,9})$/', $key) === 1 ? $key : null;
}

function sensors_source(mixed $value): string {
    return in_array($value, ['acurite', 'lacrosse'], true) ? $value : 'thermopro';
}

function sensors_source_name(string $source): string {
    if ($source === 'acurite') return 'AcuRite 592TXR';
    if ($source === 'lacrosse') return 'La Crosse IT+';
    return 'ThermoPro TX-2';
}

// "LaCrosse-BreezePro" -> "La Crosse BreezePro", for Settings.
function sensors_model_label(string $source, string $model): string {
    $model = sensors_clean_name($model);
    if ($source === 'lacrosse' && str_starts_with($model, 'LaCrosse-')) {
        return 'La Crosse ' . substr($model, strlen('LaCrosse-'));
    }
    return sensors_source_name($source);
}

function sensors_wind(array $sensor): array {
    $wind = [];
    foreach (['wind_avg_kmh' => 400, 'wind_max_kmh' => 400] as $field => $max) {
        $value = $sensor[$field] ?? null;
        if (is_numeric($value) && $value >= 0 && $value <= $max) $wind[$field] = round((float) $value, 1);
    }
    $direction = $sensor['wind_dir_deg'] ?? null;
    if (is_numeric($direction) && $direction >= 0 && $direction <= 360) $wind['wind_dir_deg'] = ((int) $direction) % 360;
    return $wind;
}

function sensors_default_label(string $source, string $channel): string {
    if ($source === 'acurite') return 'AcuRite ' . $channel;
    if ($source === 'lacrosse') return 'La Crosse ' . $channel;
    return 'Channel ' . $channel;
}

// Readings written by the receiver, keyed like "thermopro-1" / "acurite-A".
function sensors_readings(): array {
    $data = sensors_read_json(sensors_readings_path()) ?? [];
    $now = time();
    $out = ['units' => (($data['units'] ?? 'F') === 'C') ? 'C' : 'F', 'sensors' => []];
    foreach (array_slice((array) ($data['sensors'] ?? []), 0, SENSORS_MAX) as $sensor) {
        if (!is_array($sensor)) continue;
        $wind = sensors_wind($sensor);
        // A reading needs a temperature, or wind for a wind-only sensor.
        if (!is_numeric($sensor['temp_c'] ?? null) && !isset($wind['wind_avg_kmh']) && !isset($wind['wind_max_kmh'])) continue;
        $source = sensors_source($sensor['source'] ?? '');
        $channel = strtoupper((string) ($sensor['channel'] ?? ''));
        $key = sensors_valid_key($source . '-' . $channel);
        if ($key === null) continue;
        $humidity = $sensor['humidity'] ?? null;
        $out['sensors'][$key] = [
            'key' => $key,
            'source' => $source,
            'channel' => $channel,
            'default_label' => sensors_clean_name($sensor['label'] ?? '') ?: sensors_default_label($source, $channel),
            'temp_c' => is_numeric($sensor['temp_c'] ?? null) ? round((float) $sensor['temp_c'], 1) : null,
            'humidity' => is_numeric($humidity) ? (int) $humidity : null,
            'age_s' => max(0, $now - (int) ($sensor['seen'] ?? 0)),
            'model_name' => sensors_model_label($source, (string) ($sensor['model'] ?? '')),
        ] + $wind;
    }
    return $out;
}

function sensors_settings(): array {
    $data = sensors_read_json(sensors_settings_dir() . '/sensors.json') ?? [];
    $settings = [];
    foreach ((array) ($data['sensors'] ?? []) as $key => $entry) {
        if (sensors_valid_key($key) === null || !is_array($entry)) continue;
        $settings[$key] = [
            'name' => sensors_clean_name($entry['name'] ?? ''),
            'hidden' => !empty($entry['hidden']),
        ];
    }
    return $settings;
}

function sensors_storage_ok(): bool {
    $dir = sensors_settings_dir();
    return is_dir($dir) && !is_link($dir) && is_writable($dir);
}

function sensors_save_settings(array $settings): void {
    if (!sensors_storage_ok()) {
        sensors_respond(503, ['ok' => false, 'error' => 'sensor settings storage is not set up', 'hint' => SENSORS_SETUP_HINT]);
    }
    $settings = array_filter($settings, static fn($entry) => $entry['name'] !== '' || $entry['hidden']);
    $json = json_encode(['sensors' => $settings], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    $dir = sensors_settings_dir();
    $tmp = tempnam($dir, '.sensors-');
    $ok = $tmp !== false && is_string($json) && file_put_contents($tmp, $json) === strlen($json);
    if ($ok) {
        @chmod($tmp, 0640);
        $ok = rename($tmp, $dir . '/sensors.json');
    }
    if (!$ok) {
        if ($tmp !== false) @unlink($tmp);
        sensors_respond(500, ['ok' => false, 'error' => 'could not save the sensor settings']);
    }
}

// Everything Settings needs: sensors heard now plus ones only named so far.
function sensors_admin_view(): array {
    $readings = sensors_readings();
    $settings = sensors_settings();
    $list = [];
    foreach ($readings['sensors'] as $key => $reading) {
        $entry = $settings[$key] ?? ['name' => '', 'hidden' => false];
        $list[$key] = $reading + $entry + ['model' => $reading['model_name'], 'heard' => true];
    }
    foreach ($settings as $key => $entry) {
        if (isset($list[$key])) continue;
        [$source, $channel] = explode('-', $key, 2);
        $list[$key] = [
            'key' => $key, 'source' => $source, 'channel' => $channel,
            'default_label' => sensors_default_label($source, $channel),
            'temp_c' => null, 'humidity' => null, 'age_s' => null,
            'model' => sensors_source_name($source), 'heard' => false,
        ] + $entry;
    }
    ksort($list);
    return [
        'ok' => true,
        'storage_ok' => sensors_storage_ok(),
        'hint' => SENSORS_SETUP_HINT,
        'receiver' => is_file(sensors_readings_path()),
        'units' => $readings['units'],
        'sensors' => array_values($list),
    ];
}

function sensors_public(): void {
    $readings = sensors_readings();
    $settings = sensors_settings();
    $out = [];
    foreach ($readings['sensors'] as $key => $reading) {
        $entry = $settings[$key] ?? ['name' => '', 'hidden' => false];
        if ($entry['hidden']) continue;
        $out[] = [
            'key' => $key,
            'source' => $reading['source'],
            'channel' => $reading['channel'],
            'label' => $entry['name'] !== '' ? $entry['name'] : $reading['default_label'],
            'temp_c' => $reading['temp_c'],
            'humidity' => $reading['humidity'],
            'age_s' => $reading['age_s'],
        ] + array_intersect_key($reading, ['wind_avg_kmh' => 1, 'wind_max_kmh' => 1, 'wind_dir_deg' => 1]);
    }
    sensors_respond(200, ['ok' => true, 'now' => time(), 'units' => $readings['units'], 'sensors' => $out]);
}

function sensors_admin_post(array $body): void {
    $key = sensors_valid_key($body['key'] ?? null);
    if ($key === null) sensors_respond(400, ['ok' => false, 'error' => 'unknown sensor']);
    $settings = sensors_settings();
    $entry = $settings[$key] ?? ['name' => '', 'hidden' => false];
    switch ((string) ($body['action'] ?? '')) {
        case 'name':
            if (!is_string($body['name'] ?? null)) sensors_respond(400, ['ok' => false, 'error' => 'name must be text']);
            $entry['name'] = sensors_clean_name($body['name']);
            $settings[$key] = $entry;
            break;
        case 'hide':
            if (!is_bool($body['hidden'] ?? null)) sensors_respond(400, ['ok' => false, 'error' => 'hidden must be true or false']);
            $entry['hidden'] = $body['hidden'];
            $settings[$key] = $entry;
            break;
        case 'forget':
            unset($settings[$key]);
            break;
        default:
            sensors_respond(400, ['ok' => false, 'error' => 'unknown action']);
    }
    sensors_save_settings($settings);
    sensors_respond(200, sensors_admin_view());
}

function sensors_main(): void {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('Referrer-Policy: no-referrer');
    header('X-Content-Type-Options: nosniff');

    $method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    $action = (string) ($_GET['action'] ?? '');
    if ($method === 'GET' && $action === '') sensors_public();

    avian_require_admin();
    if ($method === 'GET' && $action === 'config') sensors_respond(200, sensors_admin_view());
    if ($method !== 'POST') {
        header('Allow: GET, POST');
        sensors_respond(405, ['ok' => false, 'error' => 'unsupported request']);
    }
    avian_require_json_action();
    $body = json_decode((string) file_get_contents('php://input', false, null, 0, 4096), true);
    if (!is_array($body)) sensors_respond(400, ['ok' => false, 'error' => 'expected a JSON object']);
    sensors_admin_post($body);
}

// Tests load the functions without running a request.
if (PHP_SAPI !== 'cli' || getenv('AV_SENSORS_LIB') !== '1') sensors_main();
