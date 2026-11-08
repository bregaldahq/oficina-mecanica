<?php

// Driver das Lambdas do gateway para o bin/e2e.py: chama os handlers de verdade (classes puras),
// com o banco do e2e e o segredo em memória, sem AWS.
//
// Uso: php lambda.php auth <cpf>
//      php lambda.php authorize <token> <método> <caminho>

declare(strict_types=1);

require '/gateway/vendor/autoload.php';

use Oficina\Auth\Handler\AuthCpfHandler;
use Oficina\Auth\Handler\JwtAuthorizerHandler;
use Oficina\Auth\Repository\PdoCustomerRepository;
use Oficina\Auth\Secrets\InMemorySecretsProvider;

$secrets = new InMemorySecretsProvider([
    'auth' => ['JWT_SECRET' => getenv('JWT_SECRET'), 'JWT_EXPIRATION' => getenv('JWT_EXPIRATION')],
]);

switch ($argv[1] ?? '') {
    case 'auth':
        $repository = new PdoCustomerRepository(static fn (): PDO => new PDO(
            sprintf('mysql:host=%s;port=3306;dbname=%s;charset=utf8mb4', getenv('DB_HOST'), getenv('DB_DATABASE')),
            (string) getenv('DB_USERNAME'),
            (string) getenv('DB_PASSWORD'),
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC],
        ));
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
