<?php

// Driver das Lambdas do gateway para o bin/e2e.py: chama os handlers de verdade (classes puras),
// com o segredo em memória, sem AWS. A auth-cpf consulta o cliente na rota interna da aplicação
// do e2e (OS_BASE_URL), como faz no NLB interno (docs/fase-4/CONTRATOS.md §7, no oficina-api).
//
// Uso: php lambda.php auth <cpf>
//      php lambda.php auth-os-fora <cpf>     (OS fora do ar: espera 503)
//      php lambda.php authorize <token> <método> <caminho>

declare(strict_types=1);

require '/gateway/vendor/autoload.php';

use Oficina\Auth\Handler\AuthCpfHandler;
use Oficina\Auth\Handler\JwtAuthorizerHandler;
use Oficina\Auth\Repository\HttpCustomerRepository;
use Oficina\Auth\Secrets\InMemorySecretsProvider;

$secrets = new InMemorySecretsProvider([
    'auth' => [
        'JWT_SECRET'     => getenv('JWT_SECRET'),
        'JWT_EXPIRATION' => getenv('JWT_EXPIRATION'),
        'INTERNAL_TOKEN' => getenv('INTERNAL_TOKEN'),
    ],
]);

switch ($argv[1] ?? '') {
    case 'auth':
    case 'auth-os-fora':
        $baseUrl    = $argv[1] === 'auth' ? (string) getenv('OS_BASE_URL') : 'http://127.0.0.1:1';
        $repository = new HttpCustomerRepository($baseUrl, $secrets, 'auth', timeoutSeconds: 2.0);
        $out = (new AuthCpfHandler($repository, $secrets, 'auth'))->handle([
            'body'            => json_encode(['cpf' => $argv[2] ?? '']),
            'isBase64Encoded' => false,
            'requestContext'  => ['http' => ['method' => 'POST', 'path' => '/auth/cpf']],
        ]);
        break;
    case 'authorize':
        $out = (new JwtAuthorizerHandler($secrets, 'auth'))->handle([
            'headers'        => ['authorization' => 'Bearer ' . ($argv[2] ?? '')],
            'rawPath'        => $argv[4] ?? '/',
            'requestContext' => ['http' => ['method' => $argv[3] ?? 'GET', 'path' => $argv[4] ?? '/']],
        ]);
        break;
    default:
        fwrite(STDERR, "uso: php lambda.php auth <cpf> | authorize <token> <método> <caminho>\n");
        exit(2);
}

echo json_encode($out), "\n";
