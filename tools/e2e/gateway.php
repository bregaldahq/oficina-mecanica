<?php

// Gateway local para o bin/e2e_postman.py: faz o papel do API Gateway na frente dos três
// serviços do e2e, para a coleção Postman da Fase 4 rodar sem AWS.
//
// - `POST /auth/cpf` roda a Lambda auth-cpf de verdade (a classe do oficina-gateway-auth), que
//   consulta o cliente na rota interna do OS, como no NLB;
// - `/api/billing/**` vai para o Faturamento, `/api/execution/**` para a Execução, o resto de
//   `/api/**` para o OS (docs/fase-4/CONTRATOS.md §4);
// - `/internal/**` não passa (o gateway de verdade não tem a rota);
// - `POST /__e2e/pay/{osId}` só existe aqui: paga a cobrança da OS no Mercado Pago falso, com o
//   webhook assinado, no lugar do cliente pagando no sandbox.
//
// Roda com `php -S 0.0.0.0:8080 gateway.php`, com o oficina-gateway-auth montado em /gateway.

declare(strict_types=1);

require '/gateway/vendor/autoload.php';

use Oficina\Auth\Handler\AuthCpfHandler;
use Oficina\Auth\Repository\HttpCustomerRepository;
use Oficina\Auth\Secrets\InMemorySecretsProvider;
use Oficina\Auth\Security\JwtProvider;

$env = static fn (string $key): string => (string) getenv($key);

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri    = $_SERVER['REQUEST_URI'] ?? '/';
$path   = (string) parse_url($uri, PHP_URL_PATH);
$body   = (string) file_get_contents('php://input');

/** @param array<string, string> $headers @return array{0: int, 1: string} */
$call = static function (string $method, string $url, array $headers, string $body): array {
    $lines = [];
    foreach ($headers as $name => $value) {
        $lines[] = "{$name}: {$value}";
    }
    $context = stream_context_create(['http' => [
        'method' => $method, 'header' => implode("\r\n", $lines), 'content' => $body,
        'ignore_errors' => true, 'timeout' => 20,
    ]]);
    $response = @file_get_contents($url, false, $context);
    $status   = 502;
    foreach ($http_response_header ?? [] as $line) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m) === 1) {
            $status = (int) $m[1];
        }
    }

    return [$response === false ? 502 : $status, $response === false ? '{"error":"serviço fora do ar"}' : $response];
};

$reply = static function (int $status, string $body): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo $body;
};

$secrets = new InMemorySecretsProvider(['auth' => [
    'JWT_SECRET' => $env('JWT_SECRET'), 'JWT_EXPIRATION' => $env('JWT_EXPIRATION'), 'INTERNAL_TOKEN' => $env('INTERNAL_TOKEN'),
]]);

if ($method === 'POST' && $path === '/auth/cpf') {
    $handler = new AuthCpfHandler(new HttpCustomerRepository($env('OS_URL'), $secrets, 'auth'), $secrets, 'auth');
    $out     = $handler->handle(['body' => $body, 'isBase64Encoded' => false]);
    $reply($out['statusCode'], $out['body']);

    return true;
}

if ($method === 'POST' && preg_match('#^/__e2e/pay/([\w-]+)$#', $path, $m) === 1) {
    $admin       = (new JwtProvider($env('JWT_SECRET'), 3600))->generate(['sub' => 'admin', 'role' => 'admin']);
    [, $raw]     = $call('GET', $env('OS_URL') . "/api/service-orders/{$m[1]}", ['Authorization' => "Bearer {$admin}"], '');
    $order       = json_decode($raw, true);
    if (!is_array($order) || !is_string($order['budget_id'] ?? null)) {
        $reply(409, json_encode(['error' => 'OS sem orçamento', 'os' => $order]) ?: '{}');

        return true;
    }
    // O Mercado Pago falso aprova o pagamento cujo id diz o orçamento e o valor em centavos.
    $paymentId = sprintf('fake-approved-%s-%d', $order['budget_id'], (int) round(((float) $order['total_amount']) * 100));
    $requestId = bin2hex(random_bytes(8));
    $ts        = (string) time();
    $manifest  = 'id:' . strtolower($paymentId) . ";request-id:{$requestId};ts:{$ts};";
    $signature = "ts={$ts},v1=" . hash_hmac('sha256', $manifest, $env('MP_WEBHOOK_SECRET'));
    [$status, $out] = $call('POST', $env('BILLING_URL') . "/api/billing/payments/webhook/mercadopago?data.id={$paymentId}&type=payment",
        ['x-request-id' => $requestId, 'x-signature' => $signature], '');
    $reply($status, $out);

    return true;
}

$target = match (true) {
    str_starts_with($path, '/api/billing')   => $env('BILLING_URL'),
    str_starts_with($path, '/api/execution') => $env('EXECUTION_URL'),
    str_starts_with($path, '/api/')          => $env('OS_URL'),
    default                                  => null,
};
if ($target === null) {
    $reply(404, '{"message":"Not Found"}');

    return true;
}

$forward = [];
foreach (['Authorization', 'Content-Type', 'X-Webhook-Token', 'X-Request-Id', 'X-Signature'] as $name) {
    $key = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    $value = $name === 'Content-Type' ? ($_SERVER['CONTENT_TYPE'] ?? null) : ($_SERVER[$key] ?? null);
    if (is_string($value) && $value !== '') {
        $forward[$name] = $value;
    }
}
[$status, $out] = $call($method, $target . $uri, $forward, $body);
$reply($status, $out);

return true;
