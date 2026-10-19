<?php
// AvianVisitors - local weather forecast for the collage weather badge.
//
// Forecast and place search come from Open-Meteo (free, no API key);
// US ZIP codes fall back to zippopotam.us when Open-Meteo has no match.
//
//   GET                  public: cached forecast for the configured place
//                        (refreshed at most every 30 minutes)
//   GET  ?action=config  admin: saved place, units and on/off
//   POST {action: ...}   admin + X-Avian-Action JSON:
//        set     {query, units?}        look up a city or ZIP and save the
//                                       first match; returns other matches
//        pick    {lat, lon, label}      save one of those other matches
//        units   {units: "F"|"C"}
//        enabled {enabled: bool}
//        clear                          forget the place
//
// State lives in /var/lib/avian-forecast (owned by caddy, created by
// scripts/install_services.sh and avian/thermopro/install.sh).

declare(strict_types=1);

require_once __DIR__ . '/admin-auth.php';

const FORECAST_TTL = 1800;
const FORECAST_DAYS = 5;
const FORECAST_RESPONSE_MAX = 262144;
const FORECAST_STATE_MAX = 65536;
const FORECAST_SETUP_HINT = 'run avian/thermopro/install.sh on the Pi to enable the forecast';

const FORECAST_US_STATES = [
    'AL' => 'Alabama', 'AK' => 'Alaska', 'AZ' => 'Arizona', 'AR' => 'Arkansas', 'CA' => 'California',
    'CO' => 'Colorado', 'CT' => 'Connecticut', 'DE' => 'Delaware', 'DC' => 'District of Columbia',
    'FL' => 'Florida', 'GA' => 'Georgia', 'HI' => 'Hawaii', 'ID' => 'Idaho', 'IL' => 'Illinois',
    'IN' => 'Indiana', 'IA' => 'Iowa', 'KS' => 'Kansas', 'KY' => 'Kentucky', 'LA' => 'Louisiana',
    'ME' => 'Maine', 'MD' => 'Maryland', 'MA' => 'Massachusetts', 'MI' => 'Michigan', 'MN' => 'Minnesota',
    'MS' => 'Mississippi', 'MO' => 'Missouri', 'MT' => 'Montana', 'NE' => 'Nebraska', 'NV' => 'Nevada',
    'NH' => 'New Hampshire', 'NJ' => 'New Jersey', 'NM' => 'New Mexico', 'NY' => 'New York',
    'NC' => 'North Carolina', 'ND' => 'North Dakota', 'OH' => 'Ohio', 'OK' => 'Oklahoma', 'OR' => 'Oregon',
    'PA' => 'Pennsylvania', 'RI' => 'Rhode Island', 'SC' => 'South Carolina', 'SD' => 'South Dakota',
    'TN' => 'Tennessee', 'TX' => 'Texas', 'UT' => 'Utah', 'VT' => 'Vermont', 'VA' => 'Virginia',
    'WA' => 'Washington', 'WV' => 'West Virginia', 'WI' => 'Wisconsin', 'WY' => 'Wyoming',
];

function forecast_respond(int $status, array $body): void {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function forecast_dir(): string {
    // CLI-only override keeps tests away from the real station state.
    if (PHP_SAPI === 'cli') {
        $override = getenv('AV_FORECAST_DIR');
        if (is_string($override) && $override !== '') return rtrim($override, '/');
    }
    return '/var/lib/avian-forecast';
}

function forecast_storage_ok(): bool {
    $dir = forecast_dir();
    return is_dir($dir) && !is_link($dir) && is_writable($dir);
}

function forecast_read_json(string $path): ?array {
    if (!is_file($path) || is_link($path)) return null;
    $size = filesize($path);
    if ($size === false || $size > FORECAST_STATE_MAX) return null;
    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : null;
}

function forecast_write_json(string $path, array $data): bool {
    $tmp = tempnam(dirname($path), '.forecast-');
    if ($tmp === false) return false;
    $json = json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if (!is_string($json) || file_put_contents($tmp, $json) !== strlen($json)) {
        @unlink($tmp);
        return false;
    }
    @chmod($tmp, 0640);
    if (!rename($tmp, $path)) {
        @unlink($tmp);
        return false;
    }
    return true;
}

function forecast_http_get(string $url): ?array {
    if (PHP_SAPI === 'cli') {
        // Tests replay saved API responses instead of reaching the network.
        $fixtures = getenv('AV_FORECAST_FIXTURES');
        if (is_string($fixtures) && $fixtures !== '') {
            $file = $fixtures . '/' . sha1($url) . '.json';
            $data = is_file($file) ? json_decode((string) file_get_contents($file), true) : null;
            return is_array($data) ? $data : null;
        }
    }
    if (!function_exists('curl_init')) return null;
    $handle = curl_init($url);
    if ($handle === false) return null;
    $body = '';
    curl_setopt_array($handle, [
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 4,
        CURLOPT_TIMEOUT => 8,
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
        CURLOPT_USERAGENT => 'BirdNET-Pi AvianVisitors',
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_WRITEFUNCTION => static function ($curl, string $chunk) use (&$body): int {
            if (strlen($body) + strlen($chunk) > FORECAST_RESPONSE_MAX) return 0;
            $body .= $chunk;
            return strlen($chunk);
        },
    ]);
    if (defined('CURLOPT_PROTOCOLS') && defined('CURLPROTO_HTTPS')) {
        curl_setopt($handle, CURLOPT_PROTOCOLS, CURLPROTO_HTTPS);
    }
    $completed = curl_exec($handle);
    $status = (int) curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
    curl_close($handle);
    if ($completed !== true || $status < 200 || $status >= 300) return null;
    $decoded = json_decode($body, true);
    return is_array($decoded) ? $decoded : null;
}

function forecast_units(mixed $value): string {
    return $value === 'C' ? 'C' : 'F';
}

function forecast_clean_text(mixed $value, int $max): string {
    $text = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', is_scalar($value) ? (string) $value : '');
    $text = trim((string) preg_replace('/\s+/u', ' ', (string) $text));
    return function_exists('mb_substr') ? mb_substr($text, 0, $max) : substr($text, 0, $max);
}

function forecast_valid_query(mixed $value): ?string {
    $query = forecast_clean_text($value, 80);
    if (preg_match('/^[\p{L}\p{N} ,.\'\-()]{2,80}$/u', $query) !== 1) return null;
    return $query;
}

function forecast_valid_coord(mixed $value, float $limit): ?float {
    if (!is_numeric($value)) return null;
    $number = (float) $value;
    if (!is_finite($number) || abs($number) > $limit) return null;
    return round($number, 4);
}

function forecast_place_label(array $result): string {
    $parts = [forecast_clean_text($result['name'] ?? '', 60)];
    $admin = forecast_clean_text($result['admin1'] ?? '', 40);
    if ($admin !== '' && $admin !== $parts[0]) $parts[] = $admin;
    $country = strtoupper(forecast_clean_text($result['country_code'] ?? '', 2));
    if ($country !== '' && $country !== 'US') $parts[] = $country;
    return implode(', ', array_filter($parts, static fn($part) => $part !== ''));
}

function forecast_candidate(mixed $label, mixed $lat, mixed $lon): ?array {
    $label = forecast_clean_text($label, 100);
    $lat = forecast_valid_coord($lat, 90.0);
    $lon = forecast_valid_coord($lon, 180.0);
    if ($label === '' || $lat === null || $lon === null) return null;
    return ['label' => $label, 'lat' => $lat, 'lon' => $lon];
}

// Does the text after a comma ("CA", "California", "UK", "France") match
// this Open-Meteo result?
function forecast_region_matches(array $result, string $region): bool {
    $region = strtolower(trim($region));
    if ($region === '') return true;
    $wanted = [$region];
    $abbr = strtoupper($region);
    if (isset(FORECAST_US_STATES[$abbr]) && strtoupper((string) ($result['country_code'] ?? '')) === 'US') {
        $wanted[] = strtolower(FORECAST_US_STATES[$abbr]);
    }
    if ($region === 'uk') $wanted[] = 'gb';
    if ($region === 'usa') $wanted[] = 'us';
    foreach (['admin1', 'admin2', 'country', 'country_code'] as $field) {
        $value = strtolower((string) ($result[$field] ?? ''));
        if ($value !== '' && in_array($value, $wanted, true)) return true;
    }
    return false;
}

function forecast_open_meteo_search(string $name, ?string $country = null): array {
    $params = ['name' => $name, 'count' => 10, 'language' => 'en', 'format' => 'json'];
    if ($country !== null) $params['countryCode'] = $country;
    $data = forecast_http_get('https://geocoding-api.open-meteo.com/v1/search?' . http_build_query($params));
    $results = $data['results'] ?? [];
    return is_array($results) ? array_values(array_filter($results, 'is_array')) : [];
}

function forecast_geocode(string $query): array {
    $results = [];
    if (preg_match('/^(\d{5})(?:-\d{4})?$/', $query, $zip) === 1) {
        foreach (forecast_open_meteo_search($zip[1], 'US') as $result) {
            $results[] = forecast_candidate(forecast_place_label($result) . ' ' . $zip[1],
                $result['latitude'] ?? null, $result['longitude'] ?? null);
        }
        if (!array_filter($results)) {
            $data = forecast_http_get('https://api.zippopotam.us/us/' . $zip[1]);
            foreach ((array) ($data['places'] ?? []) as $place) {
                if (!is_array($place)) continue;
                $results[] = forecast_candidate(
                    ($place['place name'] ?? '') . ', ' . ($place['state'] ?? '') . ' ' . $zip[1],
                    $place['latitude'] ?? null,
                    $place['longitude'] ?? null
                );
            }
        }
    } else {
        $parts = array_map('trim', explode(',', $query, 2));
        $found = forecast_open_meteo_search($parts[0]);
        if (isset($parts[1]) && $parts[1] !== '') {
            $filtered = array_values(array_filter($found,
                static fn($result) => forecast_region_matches($result, $parts[1])));
            if ($filtered) $found = $filtered;
        }
        foreach ($found as $result) {
            $results[] = forecast_candidate(forecast_place_label($result),
                $result['latitude'] ?? null, $result['longitude'] ?? null);
        }
    }
    $unique = [];
    foreach (array_filter($results) as $candidate) {
        $unique[$candidate['label'] . '|' . $candidate['lat'] . '|' . $candidate['lon']] = $candidate;
    }
    return array_slice(array_values($unique), 0, 5);
}

function forecast_config(): array {
    $config = forecast_read_json(forecast_dir() . '/config.json') ?? [];
    $place = null;
    if (isset($config['place']) && is_array($config['place'])) {
        $place = forecast_candidate($config['place']['label'] ?? '', $config['place']['lat'] ?? null,
            $config['place']['lon'] ?? null);
    }
    return [
        'enabled' => !empty($config['enabled']) && $place !== null,
        'units' => forecast_units($config['units'] ?? 'F'),
        'query' => forecast_clean_text($config['query'] ?? '', 80),
        'place' => $place,
    ];
}

function forecast_require_storage(): void {
    if (!forecast_storage_ok()) {
        forecast_respond(503, ['ok' => false, 'error' => 'forecast storage is not set up', 'hint' => FORECAST_SETUP_HINT]);
    }
}

function forecast_save_config(array $config): void {
    forecast_require_storage();
    if (!forecast_write_json(forecast_dir() . '/config.json', $config)) {
        forecast_respond(500, ['ok' => false, 'error' => 'could not save the forecast settings']);
    }
}

function forecast_admin_view(array $config, array $extra = []): array {
    return ['ok' => true, 'storage_ok' => forecast_storage_ok(), 'hint' => FORECAST_SETUP_HINT] + $extra + $config;
}

// Map Open-Meteo's response to the badge's small shape.
function forecast_shape(array $data): ?array {
    $current = is_array($data['current'] ?? null) ? $data['current'] : [];
    $daily = is_array($data['daily'] ?? null) ? $data['daily'] : [];
    $days = [];
    foreach (array_slice((array) ($daily['time'] ?? []), 0, FORECAST_DAYS) as $index => $date) {
        $hi = $daily['temperature_2m_max'][$index] ?? null;
        $lo = $daily['temperature_2m_min'][$index] ?? null;
        if (!is_string($date) || preg_match('/^\d{4}-\d{2}-\d{2}$/', $date) !== 1
            || !is_numeric($hi) || !is_numeric($lo)) continue;
        $pop = $daily['precipitation_probability_max'][$index] ?? null;
        $days[] = [
            'date' => $date,
            'code' => (int) ($daily['weather_code'][$index] ?? -1),
            'hi' => (int) round((float) $hi),
            'lo' => (int) round((float) $lo),
            'pop' => is_numeric($pop) ? (int) $pop : null,
        ];
    }
    if (!$days) return null;
    $now = null;
    if (is_numeric($current['temperature_2m'] ?? null)) {
        $now = [
            'temp' => (int) round((float) $current['temperature_2m']),
            'code' => (int) ($current['weather_code'] ?? -1),
            'is_day' => !empty($current['is_day']),
        ];
    }
    return ['current' => $now, 'days' => $days];
}

function forecast_fetch(array $place, string $units): ?array {
    $params = [
        'latitude' => $place['lat'],
        'longitude' => $place['lon'],
        'current' => 'temperature_2m,weather_code,is_day',
        'daily' => 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
        'temperature_unit' => $units === 'C' ? 'celsius' : 'fahrenheit',
        'timezone' => 'auto',
        'forecast_days' => FORECAST_DAYS,
    ];
    $data = forecast_http_get('https://api.open-meteo.com/v1/forecast?' . http_build_query($params));
    return is_array($data) ? forecast_shape($data) : null;
}

function forecast_cached(?array $cache, string $key): ?array {
    if (!is_array($cache) || ($cache['key'] ?? '') !== $key || !is_array($cache['forecast'] ?? null)) return null;
    return $cache;
}

// Where the sun and moon are worked out for the badge and the sunrise/sunset
// theme: the forecast place, else the station's own coordinates from
// birdnet.conf. Rounded to ~1 km, which is plenty for sunrise times.
function forecast_station_conf(): string {
    // CLI-only override keeps tests away from the real station config.
    if (PHP_SAPI === 'cli') {
        $override = getenv('AV_BIRDNET_CONF');
        if (is_string($override) && $override !== '') return $override;
    }
    return '/etc/birdnet/birdnet.conf';
}

function forecast_sky(array $config): ?array {
    $lat = $config['place']['lat'] ?? null;
    $lon = $config['place']['lon'] ?? null;
    if ($lat === null || $lon === null) {
        $path = forecast_station_conf();
        $text = is_file($path) && is_readable($path) && filesize($path) < 65536 ? (string) file_get_contents($path) : '';
        if (preg_match('/^\s*LATITUDE\s*=\s*"?(-?[0-9.]+)"?\s*$/m', $text, $m)) $lat = (float) $m[1];
        if (preg_match('/^\s*LONGITUDE\s*=\s*"?(-?[0-9.]+)"?\s*$/m', $text, $m)) $lon = (float) $m[1];
    }
    $lat = forecast_valid_coord($lat, 90.0);
    $lon = forecast_valid_coord($lon, 180.0);
    // 0,0 is BirdNET-Pi's unset default, not a real station.
    if ($lat === null || $lon === null || ($lat == 0.0 && $lon == 0.0)) return null;
    return ['lat' => round($lat, 2), 'lon' => round($lon, 2)];
}

function forecast_public(): void {
    $config = forecast_config();
    $sky = forecast_sky($config);
    if (!$config['enabled']) {
        forecast_respond(200, ['ok' => true, 'enabled' => false, 'units' => $config['units'], 'sky' => $sky]);
    }
    $place = $config['place'];
    $key = $place['lat'] . ',' . $place['lon'] . ',' . $config['units'];
    $cachePath = forecast_dir() . '/cache.json';
    $base = ['ok' => true, 'enabled' => true, 'place' => $place['label'], 'units' => $config['units'], 'sky' => $sky];

    $cache = forecast_cached(forecast_read_json($cachePath), $key);
    if ($cache && time() - (int) ($cache['fetched'] ?? 0) < FORECAST_TTL) {
        forecast_respond(200, $base + ['updated' => (int) $cache['fetched']] + $cache['forecast']);
    }

    // One refresh at a time; a second viewer waits for it and reuses it.
    $lock = forecast_storage_ok() ? @fopen(forecast_dir() . '/fetch.lock', 'c') : false;
    if ($lock !== false) flock($lock, LOCK_EX);
    $cache = forecast_cached(forecast_read_json($cachePath), $key);
    if ($cache && time() - (int) ($cache['fetched'] ?? 0) < FORECAST_TTL) {
        forecast_respond(200, $base + ['updated' => (int) $cache['fetched']] + $cache['forecast']);
    }
    $fresh = forecast_fetch($place, $config['units']);
    if ($fresh !== null) {
        $now = time();
        if (forecast_storage_ok()) {
            forecast_write_json($cachePath, ['key' => $key, 'fetched' => $now, 'forecast' => $fresh]);
        }
        forecast_respond(200, $base + ['updated' => $now] + $fresh);
    }
    if ($cache) {
        forecast_respond(200, $base + ['updated' => (int) $cache['fetched'], 'stale' => true] + $cache['forecast']);
    }
    forecast_respond(503, ['ok' => false, 'enabled' => true, 'error' => 'forecast unavailable', 'sky' => $sky]);
}

function forecast_admin_post(array $body): void {
    $config = forecast_config();
    switch ((string) ($body['action'] ?? '')) {
        case 'set':
            $query = forecast_valid_query($body['query'] ?? '');
            if ($query === null) forecast_respond(400, ['ok' => false, 'error' => 'enter a city or ZIP code']);
            forecast_require_storage();
            $matches = forecast_geocode($query);
            if (!$matches) forecast_respond(404, ['ok' => false, 'error' => 'no place found for "' . $query . '"']);
            if (array_key_exists('units', $body)) $config['units'] = forecast_units($body['units']);
            $config['query'] = $query;
            $config['place'] = $matches[0];
            $config['enabled'] = true;
            forecast_save_config($config);
            forecast_respond(200, forecast_admin_view(forecast_config(), ['matches' => $matches]));
            break;
        case 'pick':
            $place = forecast_candidate($body['label'] ?? '', $body['lat'] ?? null, $body['lon'] ?? null);
            if ($place === null) forecast_respond(400, ['ok' => false, 'error' => 'invalid place']);
            $config['place'] = $place;
            $config['query'] = $place['label'];
            $config['enabled'] = true;
            forecast_save_config($config);
            forecast_respond(200, forecast_admin_view(forecast_config()));
            break;
        case 'units':
            $config['units'] = forecast_units($body['units'] ?? 'F');
            forecast_save_config($config);
            forecast_respond(200, forecast_admin_view(forecast_config()));
            break;
        case 'enabled':
            if (!is_bool($body['enabled'] ?? null)) {
                forecast_respond(400, ['ok' => false, 'error' => 'enabled must be true or false']);
            }
            if ($body['enabled'] && $config['place'] === null) {
                forecast_respond(400, ['ok' => false, 'error' => 'set a city or ZIP code first']);
            }
            $config['enabled'] = $body['enabled'];
            forecast_save_config($config);
            forecast_respond(200, forecast_admin_view(forecast_config()));
            break;
        case 'clear':
            forecast_save_config(['enabled' => false, 'units' => $config['units'], 'query' => '', 'place' => null]);
            forecast_respond(200, forecast_admin_view(forecast_config()));
            break;
    }
    forecast_respond(400, ['ok' => false, 'error' => 'unknown action']);
}

function forecast_main(): void {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('Referrer-Policy: no-referrer');
    header('X-Content-Type-Options: nosniff');

    $method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    $action = (string) ($_GET['action'] ?? '');
    if ($method === 'GET' && $action === '') forecast_public();

    avian_require_admin();
    if ($method === 'GET' && $action === 'config') {
        forecast_respond(200, forecast_admin_view(forecast_config()));
    }
    if ($method !== 'POST') {
        header('Allow: GET, POST');
        forecast_respond(405, ['ok' => false, 'error' => 'unsupported request']);
    }
    avian_require_json_action();
    $body = json_decode((string) file_get_contents('php://input', false, null, 0, 4096), true);
    if (!is_array($body)) forecast_respond(400, ['ok' => false, 'error' => 'expected a JSON object']);
    forecast_admin_post($body);
}

// Tests load the functions without running a request.
if (PHP_SAPI !== 'cli' || getenv('AV_FORECAST_LIB') !== '1') forecast_main();
